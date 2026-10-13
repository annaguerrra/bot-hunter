"""Testes das trocas de fonte, isolamento e cotas; sem chamadas reais."""
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import requests
from jobhunter import automatic, gemini, providers, matching, salary
from jobhunter.gemini_usage import GeminiBudget
from jobhunter.google_usage import GoogleBudget
from jobhunter.storage import Store
from jobhunter.usage import UsageBudget, BudgetExceeded
from web import validate_filters


def response(status=200, data=None):
    value = requests.Response()
    value.status_code = status
    value._content = json.dumps(data or {'candidates': [{'content': {'parts': [{'text': '{"action_ids": ["history"], "tips": ["Reveja requisitos antes de aplicar."]}'}]}}]}).encode()
    return value


def example(title='Production Engineer', pay='BRL 8,000 per month', country='BR'):
    value = providers.make_job(title, 'Example', 'Curitiba, Brazil', 'https://example.org/job', 'Example', country=country, salary=pay)
    value['match'] = matching.assess(value, 'both', ['production engineer'], True, [])
    value['salary_check'] = salary.evaluate(value, 7000)
    return value


class AutomaticTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'GEMINI_ENABLED': 'false', 'GEMINI_AUTO_FALLBACK': 'true',
            'GEMINI_API_KEY': 'fake-test-key', 'SERPAPI_API_KEY': 'fake-serp', 'JOOBLE_API_KEY_BR': 'fake-br', 'AUTO_SOURCE_ROUTING': 'true'}, clear=True)
        self.environment.start()
        # Nenhum teste pode alcançar a internet, mesmo com credenciais fictícias.
        for method in ('get', 'post'):
            guard = patch.object(requests, method, side_effect=AssertionError('Chamada externa não simulada'))
            guard.start()
            self.addCleanup(guard.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / 'hunter.sqlite')
        self.owner = self.store.register('QA', 'qa@example.org', 'strong-test-password')['id']
        self.member = self.store.register('Other', 'other@example.org', 'strong-test-password')['id']
        self.companies = self.store.companies(self.owner)
        self.usage = UsageBudget(self.store.path)
        self.budget = GeminiBudget(self.usage, self.owner)
        self.filters = validate_filters({'keywords': 'production engineer', 'sources': ['jooble'], 'country': 'BR', 'auto_sources': True}, self.companies)

    def tearDown(self):
        self.directory.cleanup()
        self.environment.stop()

    def exhaust(self):
        self.usage.set_limits(1, 5, 5)
        self.usage.reserve(self.owner, 'BR', 'fake-br')
        GoogleBudget(self.usage).configure(1, 250)
        GoogleBudget(self.usage).reserve()

    def test_fallback_uses_company_when_primary_quota_is_empty(self):
        self.exhaust()
        with patch.dict(providers.COMPANY_PROVIDERS, {'smartrecruiters': lambda company, query: ([example()], [])}), patch.object(providers, 'enrich_company_jobs', side_effect=lambda company, jobs, filters: (jobs, [])), patch.object(requests, 'post') as network, patch.object(requests, 'get') as get:
            result = providers.run_search(self.filters, self.companies[:1], usage=self.usage, user_id=self.owner)
        network.assert_not_called()
        get.assert_not_called()
        self.assertEqual(len(result['jobs']), 1)
        self.assertTrue(result['routing']['substituted'])
        self.assertEqual(result['routing']['decisions'][-1]['source'], 'companies')

    def test_cached_jooble_results_are_used_without_spending_exhausted_quota(self):
        self.exhaust()
        for keyword in matching.expand_queries(self.filters['keywords'], self.filters['profile'], 'BR', True, limit=6):
            query = {'keywords': keyword, 'location': providers.query_location(self.filters, 'BR'), 'page': 1, 'ResultOnPage': 100, 'radius': '0'}
            self.usage.remember('fake-br', query, [{'title': 'Production Engineer', 'company': 'Example', 'location': 'Curitiba, Brazil', 'link': 'https://example.org/cached', 'salary': 'BRL 8,000 per month'}])
        with patch.object(requests, 'post') as post, patch.object(requests, 'get') as get:
            result = providers.run_search(self.filters, [], usage=self.usage, user_id=self.owner)
        post.assert_not_called()
        get.assert_not_called()
        self.assertEqual(result['routing']['decisions'][0]['status'], 'cache')
        self.assertEqual(len(result['jobs']), 1)
        self.assertEqual(self.usage.snapshot(self.owner, {'BR': 'fake-br'})['used_today'], 1)

    def test_all_searches_exhausted_activate_scoped_gemini_assistance(self):
        self.exhaust()
        with patch.object(requests, 'post', return_value=response()) as post, patch.object(requests, 'get') as get:
            result = providers.run_search(self.filters, [], usage=self.usage, user_id=self.owner)
        get.assert_not_called()
        post.assert_called_once()
        self.assertNotIn('tools', post.call_args.kwargs['json'])
        self.assertEqual(post.call_args.kwargs['json']['generationConfig']['maxOutputTokens'], 2048)
        self.assertEqual(os.environ['GEMINI_ENABLED'], 'false')
        self.assertEqual(result['jobs'], [])
        self.assertEqual(result['routing']['state'], 'activities')
        self.assertEqual(result['routing']['activities'][0]['id'], 'history')
        self.assertEqual(result['routing']['decisions'][-1]['status'], 'assistance')
        self.assertEqual(self.budget.snapshot()['used_today'], 1)

    def test_gemini_quota_preserves_offline_activities_and_private_saved_jobs(self):
        self.exhaust()
        self.budget.configure(1, 6, 60, True)
        self.budget.reserve(100)
        self.store.favorite(example(), user_id=self.owner)
        foreign = {**example(), 'id': 'foreign', 'title': 'Production Engineer private other'}
        self.store.favorite(foreign, user_id=self.member)
        with patch.object(requests, 'post') as post, patch.object(requests, 'get') as get:
            result = providers.run_search(self.filters, [], usage=self.usage, user_id=self.owner)
        post.assert_not_called()
        get.assert_not_called()
        self.assertEqual(result['routing']['state'], 'activities')
        self.assertEqual(len(result['routing']['saved_opportunities']), 1)
        self.assertNotIn('foreign', json.dumps(result))
        self.assertTrue(any('LinkedIn' in action['name'] for action in result['routing']['activities']))
        self.assertEqual(result['jobs'], [])

    def test_renewed_budget_restores_primary_without_changing_preferences(self):
        self.exhaust()
        self.usage.clock = lambda: datetime(2030, 2, 1, 12, tzinfo=timezone.utc).timestamp()
        def collect(filters, companies, **kwargs):
            self.assertEqual(filters['sources'], ['jooble'])
            self.assertFalse(filters['_cache_only'])
            return {'jobs': [example()]}
        result = automatic.search(self.filters, [], self.usage, self.owner, collect)
        self.assertFalse(result['routing']['substituted'])
        self.assertEqual(self.filters['sources'], ['jooble'])

    def test_country_is_not_changed_when_only_other_key_is_available(self):
        with patch.dict(os.environ, {'JOOBLE_API_KEY_BR': '', 'JOOBLE_API_KEY_NO': 'fake-no'}), patch.object(requests, 'post', return_value=response()) as post, patch.object(requests, 'get', return_value=response(data={'jobs_results': []})):
            result = providers.run_search(self.filters, [], usage=self.usage, user_id=self.owner)
        self.assertFalse(result['routing']['resources']['jooble']['configured'])
        self.assertTrue(all('no.jooble.org' not in call.args[0] for call in post.call_args_list))

    def test_automatic_ai_does_not_accept_paid_search_model(self):
        with patch.dict(os.environ, {'GEMINI_AUTO_SEARCH_MODEL': 'gemini-3.1-flash-lite'}), gemini.usage_scope(self.usage, self.owner, automatic=True), patch.object(requests, 'post') as post:
            with self.assertRaises(gemini.GeminiError):
                gemini.generate('Search', search=True)
        post.assert_not_called()
        self.assertEqual(self.budget.snapshot()['used_today'], 0)

    def test_unrecognized_action_ids_cannot_inject_links(self):
        self.exhaust()
        data = {'candidates': [{'content': {'parts': [{'text': json.dumps({'action_ids': ['https://evil.invalid'], 'tips': []})}]}}]}
        with patch.object(requests, 'post', return_value=response(data=data)):
            result = providers.run_search(self.filters, [], usage=self.usage, user_id=self.owner)
        self.assertNotIn('evil.invalid', json.dumps(result))

    def test_disabled_automatic_mode_preserves_manual_source_selection(self):
        with patch.object(providers, '_run_search', return_value={'jobs': []}) as collect, patch.object(automatic, 'search') as choose:
            providers.run_search({**self.filters, 'auto_sources': False}, [], usage=self.usage, user_id=self.owner)
        choose.assert_not_called()
        self.assertEqual(collect.call_args.args[0]['sources'], ['jooble'])

    def test_provider_failure_falls_back_without_calling_gemini(self):
        with patch.object(providers, 'jooble', side_effect=requests.Timeout('private-error')), patch.dict(providers.COMPANY_PROVIDERS, {'smartrecruiters': lambda company, query: ([example()], [])}), patch.object(providers, 'enrich_company_jobs', side_effect=lambda company, jobs, filters: (jobs, [])):
            result = providers.run_search(self.filters, self.companies[:1], usage=self.usage, user_id=self.owner)
        self.assertEqual(result['routing']['decisions'][0]['status'], 'error')
        self.assertNotIn('private-error', json.dumps(result))
        self.assertEqual(len(result['jobs']), 1)
        self.assertEqual(self.budget.snapshot()['used_today'], 0)

    def test_fallback_preserves_salary_and_specialty_filters(self):
        with patch.object(providers, 'jooble', return_value=([example('Coordenador de Cozinha'), example(pay='BRL 2,600 per month')], [])), patch.dict(providers.COMPANY_PROVIDERS, {'smartrecruiters': lambda company, query: ([example(pay='')], [])}), patch.object(providers, 'enrich_company_jobs', side_effect=lambda company, jobs, filters: (jobs, [])):
            result = providers.run_search(self.filters, self.companies[:1], usage=self.usage, user_id=self.owner)
        self.assertEqual(result['jobs'], [])
        self.assertEqual(len(result['review_jobs']), 1)
        self.assertTrue(result['routing']['substituted'])
        self.assertEqual(result['review_jobs'][0]['salary_check']['status'], 'review')

    def test_manual_gemini_calls_respect_the_same_quota(self):
        self.budget.configure(1, 6, 60, False)
        self.budget.reserve(100)
        with patch.dict(os.environ, {'GEMINI_ENABLED': 'true'}), gemini.usage_scope(self.usage, self.owner):
            with self.assertRaises(BudgetExceeded):
                gemini.generate('manual search', search=True)

    def test_assistance_permission_disabled_preserves_offline_activities(self):
        self.exhaust()
        self.budget.configure(2, 6, 60, False)
        result = providers.run_search(self.filters, [], usage=self.usage, user_id=self.owner)
        self.assertEqual(result['routing']['state'], 'activities')
        self.assertEqual(self.budget.snapshot()['used_today'], 0)
        self.assertTrue(result['routing']['activities'])

    def test_only_admin_can_change_gemini_policy_and_counts_are_preserved(self):
        from web import create_app
        app = create_app(self.store.path)
        try:
            owner, member = app.test_client(), app.test_client()
            def login(client, email):
                csrf = client.get('/api/auth/session').json['csrf']
                result = client.post('/api/auth/login', headers={'X-Hunter-CSRF': csrf}, json={'email': email, 'password': 'strong-test-password'})
                self.assertEqual(result.status_code, 200)
                return {'X-Hunter-CSRF': result.json['csrf']}
            owner_headers = login(owner, 'qa@example.org')
            member_headers = login(member, 'other@example.org')
            self.budget.reserve(100)
            policy = {'action': 'gemini', 'user_daily': 2, 'global_daily': 6, 'monthly': 60, 'auto_enabled': False}
            self.assertEqual(member.post('/api/integrations/usage', headers=member_headers, json=policy).status_code, 403)
            self.assertEqual(owner.post('/api/integrations/usage', headers=owner_headers, json={**policy, 'auto_enabled': 'false'}).status_code, 400)
            self.assertEqual(owner.post('/api/integrations/usage', headers=owner_headers, json=policy).status_code, 200)
            self.assertEqual(self.budget.snapshot()['used_today'], 1)
            self.assertFalse(self.budget.snapshot()['auto_enabled'])
        finally:
            app.extensions['executor'].shutdown(wait=True)

    def test_new_gemini_cache_is_private_and_does_not_consume_quota_twice(self):
        with patch.object(requests, 'post', return_value=response()) as post:
            with gemini.usage_scope(self.usage, self.owner, automatic=True):
                gemini.generate('same prompt')
                gemini.generate('same prompt')
            with gemini.usage_scope(self.usage, self.member, automatic=True):
                gemini.generate('same prompt')
        self.assertEqual(post.call_count, 2)
        self.assertEqual(self.budget.snapshot()['used_today'], 1)
        self.assertEqual(GeminiBudget(self.usage, self.member).snapshot()['used_today'], 1)

    def test_429_pauses_attempts_until_retry_after_without_leaking_response(self):
        failure = response(429, {'error': 'private-provider-body'})
        failure.headers['Retry-After'] = '120'
        with patch.object(requests, 'post', return_value=failure) as post, gemini.usage_scope(self.usage, self.owner, automatic=True):
            with self.assertRaises(gemini.GeminiError) as error:
                gemini.generate('one')
            with self.assertRaises(BudgetExceeded):
                gemini.generate('two')
        self.assertNotIn('private-provider-body', str(error.exception))
        post.assert_called_once()
        self.assertEqual(self.budget.snapshot()['used_today'], 1)
        self.assertTrue(self.budget.snapshot()['blocked'])

    def test_concurrent_reservations_cannot_exceed_global_cap(self):
        self.budget.configure(100, 2, 60, True)
        gate = threading.Barrier(6)
        def reserve(index):
            gate.wait()
            try:
                GeminiBudget(self.usage, self.owner if index % 2 else self.member).reserve(100)
                return True
            except BudgetExceeded:
                return False
        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(sum(pool.map(reserve, range(6))), 2)
        self.assertEqual(self.budget.snapshot()['global_used_today'], 2)

    def test_monthly_and_token_limits_survive_restarts(self):
        self.budget.configure(100, 100, 1, True)
        self.budget.reserve(100)
        restarted = GeminiBudget(UsageBudget(self.store.path), self.member)
        with self.assertRaises(BudgetExceeded):
            restarted.reserve(100)
        self.assertEqual(restarted.snapshot()['used_month'], 1)
        self.budget.configure(100, 100, 60, True)
        with self.assertRaises(BudgetExceeded):
            self.budget.reserve(200000)
        self.assertEqual(self.budget.snapshot()['used_today'], 1)


if __name__ == '__main__':
    unittest.main()
