"""Catálogo, ATS e orientação sem consumo de APIs, com contas isoladas."""
import copy
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import requests

from web import create_app, validate_filters
from jobhunter import career_resources as career, company_catalog as catalog, discovery, gemini, providers, salary
from jobhunter.storage import Store
from jobhunter.usage import UsageBudget

FORM = {'keywords': 'product engineer', 'profile': 'product', 'sources': ['companies']}
ASHBY = {'id': 7, 'enabled': 1, 'name': 'Example', 'provider': 'ashby', 'identifier': 'example', 'url': 'https://jobs.ashbyhq.com/example'}


def posting(**extra):
    return {'title': 'Product Engineer', 'isListed': True, 'jobUrl': 'https://jobs.ashbyhq.com/example/1',
            'applyUrl': 'https://jobs.ashbyhq.com/example/1/application', 'location': 'Austin, TX',
            'address': {'postalAddress': {'addressCountry': 'USA', 'addressRegion': 'Texas', 'addressLocality': 'Austin'}}, **extra}


class PublicBoardTests(unittest.TestCase):
    def setUp(self):
        self.filters = validate_filters(FORM, [ASHBY])

    def fetch(self, data):
        with patch.object(providers, 'public_json', return_value=data) as fetch:
            jobs, notes = providers.ashby(ASHBY, {**self.filters, 'keywords': ['one', 'two', 'three']})
        self.assertEqual(fetch.call_count, 1)
        self.assertIn('includeCompensation', fetch.call_args.args[1])
        return jobs

    def test_ashby_detection_is_explicit_and_validates_tenant(self):
        self.assertEqual(providers.detect_provider('https://jobs.ashbyhq.com/hadrian-automation/1'), ('ashby', 'hadrian-automation'))
        self.assertEqual(providers.detect_provider('https://jobs.ashbyhq.com.evil.example/tenant'), ('website', ''))
        for url in ['https://jobs.ashbyhq.com/%2e%2e', 'https://jobs.ashbyhq.com/bad%20tenant']:
            with self.assertRaises(ValueError): providers.detect_provider(url)
        with patch.object(providers, 'public_json') as fetch, self.assertRaises(ValueError):
            providers.ashby({**ASHBY, 'identifier': '../private'}, self.filters)
        fetch.assert_not_called()

    def test_optional_fields_hidden_jobs_and_safe_application_link(self):
        jobs = self.fetch({'jobs': [posting(isListed=False), posting(isListed=None), posting(), posting(title='Other', jobUrl='javascript:evil', applyUrl=None), 'bad']})
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['country'], 'US')
        self.assertEqual(jobs[0]['link'], posting()['applyUrl'])
        self.assertEqual(salary.evaluate(jobs[0], 7000)['status'], 'review')

    def test_yearly_salary_conversion_and_bonus_exclusion(self):
        compensation = {'summaryComponents': [{'compensationType': 'Bonus', 'minValue': 500000},
            {'compensationType': 'Salary', 'minValue': 24000, 'maxValue': 36000, 'currencyCode': 'USD', 'interval': '1 YEAR'}]}
        job = self.fetch({'jobs': [posting(compensation=compensation)]})[0]
        result = salary.evaluate(job, 7000, rate_fetch=lambda _: (5, '2026-10-12'))
        self.assertEqual(result['status'], 'eligible')
        self.assertEqual(result['monthly_brl'], 10000)
        self.assertEqual(job['salary_data']['period'], 'YEAR')

    def test_unknown_interval_and_ambiguous_tiers_require_review(self):
        component = {'compensationType': 'Salary', 'minValue': 100000, 'currencyCode': 'USD', 'interval': 'UNKNOWN'}
        job = self.fetch({'jobs': [posting(compensation={'summaryComponents': [component]})]})[0]
        self.assertEqual(salary.evaluate(job, 7000)['status'], 'review')
        self.assertEqual(providers.ashby_salary({'summaryComponents': [component, component]}), {})
        self.assertEqual(providers.ashby_salary({'summaryComponents': [{**component, 'interval': '1 YEAR', 'summary': 'Estimated based on experience'}]}), {})

    def test_remote_secondary_locations_and_unknown_country(self):
        jobs = self.fetch({'jobs': [posting(workplaceType='Remote', secondaryLocations=[{'location': 'Toronto, Canada', 'address': {'addressCountry': 'CAN'}}]),
                                   posting(address=None, location='Unknown', jobUrl='https://jobs.ashbyhq.com/example/2', applyUrl=None)]})
        self.assertTrue(jobs[0]['remote'])
        self.assertEqual([job['country'] for job in jobs], ['US', 'CA', ''])
        self.assertNotEqual(jobs[0]['id'], jobs[1]['id'])
        self.assertFalse(providers.location_matches(jobs[2], {**self.filters, 'country': 'BR'}))

    def test_empty_and_malformed_response(self):
        self.assertEqual(self.fetch({'jobs': []}), [])
        for data in [None, [], {}, {'jobs': {}}]:
            with self.assertRaises(ValueError): self.fetch(data)

    def test_http_and_timeout_failures_preserve_other_companies(self):
        companies = [ASHBY, {**ASHBY, 'id': 8, 'name': 'Other', 'identifier': 'other'}]
        for error in [requests.Timeout(), ValueError('json'), requests.HTTPError(response=type('Response', (), {'status_code': 404})()), requests.HTTPError(response=type('Response', (), {'status_code': 429})())]:
            with patch.object(providers, 'fetch_company_jobs', side_effect=[error, ([providers.make_job('Product Engineer', 'Other', 'Brazil', 'https://example.org/2', 'Other', country='BR')], [])]):
                result = providers.run_search({**self.filters, 'company_ids': [7, 8]}, companies)
            self.assertEqual(result['reports'][0]['status'], 'error')
            self.assertEqual(len(result['review_jobs']), 1)

    def test_public_cache_expires_and_does_not_reserve_any_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.sqlite'; Store(path)
            now = [1000]; usage = UsageBudget(path, clock=lambda: now[0])
            with patch.object(providers, 'public_json', return_value={'jobs': [posting()]}) as fetch, patch.object(usage, 'reserve', side_effect=AssertionError('quota')):
                first, _ = providers.fetch_company_jobs(ASHBY, self.filters, usage)
                second, notes = providers.fetch_company_jobs(ASHBY, self.filters, usage)
                self.assertEqual(first, second); self.assertEqual(fetch.call_count, 1)
                self.assertTrue(any('cache' in note for note in notes))
                now[0] += 43201; providers.fetch_company_jobs(ASHBY, self.filters, usage)
                self.assertEqual(fetch.call_count, 2)

    def test_explicit_free_mode_never_falls_back_or_ranks_with_ai(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.sqlite'; Store(path)
            usage = UsageBudget(path)
            with patch.object(providers, 'jooble', side_effect=AssertionError('Jooble')), patch.object(providers, 'google_jobs', side_effect=AssertionError('Google')), patch.object(gemini, 'search_jobs', side_effect=AssertionError('Gemini')), patch.object(gemini, 'rank_jobs', side_effect=AssertionError('ranking')), patch('jobhunter.automatic.search', side_effect=AssertionError('fallback')), patch.object(providers, 'public_json', return_value={'jobs': [posting()]}) as fetch, patch.object(usage, 'reserve', side_effect=AssertionError('quota')):
                result = providers.run_search({**self.filters, 'sources': ['jooble', 'google', 'gemini'], 'auto_sources': True, 'free_exploration': True}, [ASHBY], usage=usage)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(len(result['review_jobs']), 1)

    def test_company_limit_is_separate_and_selection_order_is_preserved(self):
        companies = [{**ASHBY, 'id': n, 'identifier': f'example-{n}'} for n in range(15)]
        selected = list(reversed(range(15)))
        with patch.dict(os.environ, {'COMPANY_SEARCH_LIMIT': '10'}), patch.object(providers, 'fetch_company_jobs', return_value=([], [])) as fetch:
            result = providers.run_search({**self.filters, 'company_ids': selected}, companies)
        self.assertEqual(fetch.call_count, 10)
        self.assertEqual([call.args[0]['id'] for call in fetch.call_args_list], selected[:10])
        self.assertIn('5 empresas', result['reports'][-1]['notes'][0])


class CatalogCareerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.directory.name) / 'db.sqlite'); self.app.testing = True
        self.store = self.app.extensions['store']
        self.client, self.headers, self.owner = self.register('first@example.org')

    def tearDown(self):
        self.app.extensions['executor'].shutdown(wait=True); self.directory.cleanup()

    def register(self, email):
        client = self.app.test_client()
        csrf = client.get('/api/auth/session').json['csrf']
        result = client.post('/api/auth/register', json={'email': email, 'name': 'Test person', 'password': 'a-long-test-password'}, headers={'X-Hunter-CSRF': csrf})
        self.assertEqual(result.status_code, 201)
        return client, {'X-Hunter-CSRF': result.json['csrf']}, result.json['user']['id']

    def test_catalog_has_twenty_integrations_and_three_external_links(self):
        items = catalog.suggestions()
        self.assertEqual(len(items), 23)
        self.assertEqual(sum(item['status'] == 'validated' for item in items), 20)
        self.assertEqual(sum(item['provider'] == 'ashby' for item in items), 5)
        self.assertEqual(len(self.store.companies(self.owner)), 5)
        response = self.client.get('/api/companies/catalog').json
        self.assertEqual(len(response['companies']), 10); self.assertEqual(response['total'], 23)

    def test_filters_and_pagination_do_not_access_external_apis(self):
        with patch.object(providers, 'public_json', side_effect=AssertionError('network')), patch.object(gemini, 'generate', side_effect=AssertionError('AI')):
            result = self.client.get('/api/companies/catalog?provider=ashby&country=CA').json
            self.assertEqual([item['name'] for item in result['companies']], ['Eli Health'])
            first = self.client.get('/api/companies/catalog').json['companies']
            second = self.client.get('/api/companies/catalog?offset=10').json['companies']
            self.assertFalse({item['catalog_id'] for item in first} & {item['catalog_id'] for item in second})
            self.assertEqual(self.client.get('/api/companies/catalog?provider=bad').status_code, 400)
            self.assertEqual(self.client.get('/api/companies/catalog?offset=-1').status_code, 400)

    def test_bulk_import_is_idempotent_and_does_not_activate_paused_company(self):
        paused = self.store.companies(self.owner)[0]; self.store.update_company(paused['id'], enabled=False, user_id=self.owner)
        choices = [':'.join(catalog.identity(paused)), next(item['catalog_id'] for item in catalog.suggestions() if item['name'] == 'SGS')]
        for expected in [1, 0]:
            with patch.object(providers, 'public_json', side_effect=AssertionError('network')):
                response = self.client.post('/api/companies/catalog', json={'ids': choices}, headers=self.headers)
            self.assertEqual(response.status_code, 200); self.assertEqual(response.json['added'], expected)
        self.assertEqual(len(self.store.companies(self.owner)), 6)
        self.assertFalse(next(item for item in self.store.companies(self.owner) if item['id'] == paused['id'])['enabled'])

    def test_removed_company_is_not_reintroduced_by_catalog_or_initialization(self):
        item = self.store.companies(self.owner)[0]; self.store.update_company(item['id'], remove=True, user_id=self.owner)
        self.client.get('/api/companies/catalog'); Store(self.store.path)
        self.assertNotIn(item['id'], [company['id'] for company in self.store.companies(self.owner)])
        self.assertEqual(len(self.store.companies(self.owner)), 4)

    def test_simultaneous_insertions_do_not_duplicate_tenant(self):
        item = next(item for item in catalog.suggestions() if item['name'] == 'SGS')
        with ThreadPoolExecutor(max_workers=4) as executor:
            ids = list(executor.map(lambda _: self.store.add_company(item, self.owner), range(4)))
        self.assertEqual(len(set(ids)), 1)
        changed_url = {**item, 'url': item['url'] + '/', 'identifier': item['identifier'].lower()}
        self.assertEqual(self.store.add_company(changed_url, self.owner), ids[0])

    def test_registration_cap_rolls_back_whole_batch(self):
        self.store.add_companies([{**ASHBY, 'identifier': f'tenant-{n}', 'url': f'https://jobs.ashbyhq.com/tenant-{n}'} for n in range(94)], self.owner)
        with self.assertRaises(ValueError): self.store.add_companies([{**ASHBY, 'identifier': 'one', 'url': ASHBY['url'] + '/one'}, {**ASHBY, 'identifier': 'two', 'url': ASHBY['url'] + '/two'}], self.owner)
        self.assertEqual(len(self.store.companies(self.owner)), 99)

    def test_external_and_pending_items_cannot_be_activated(self):
        manual = next(item for item in catalog.suggestions() if item['status'] == 'manual_only')
        for ids in [[manual['catalog_id']], ['ashby:invented'], []]:
            self.assertEqual(self.client.post('/api/companies/catalog', json={'ids': ids}, headers=self.headers).status_code, 400)
        pending = {**ASHBY, 'catalog_id': 'ashby:pending', 'status': 'api_pending'}
        with patch.object(catalog, 'suggestions', return_value=[pending]):
            self.assertEqual(self.client.post('/api/companies/catalog', json={'ids': ['ashby:pending']}, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post('/api/companies/catalog', json=['bad'], headers=self.headers).status_code, 400)

    def test_public_resources_are_included_without_private_data_in_vercel(self):
        config = json.loads(Path('vercel.json').read_text('utf-8'))
        excluded = config['functions']['app.py']['excludeFiles']
        self.assertIn('data/**', excluded)
        self.assertNotIn('resources/', excluded)
        self.assertTrue(Path('resources/companies.json').is_file())
        self.assertTrue(Path('resources/career_resources.json').is_file())

    def test_career_filters_sources_and_guidance_work_without_apis(self):
        with patch.object(providers, 'public_json', side_effect=AssertionError('network')), patch.object(gemini, 'generate', side_effect=AssertionError('AI')):
            result = self.client.get('/api/career?category=linkedin&q=foto').json
            self.assertTrue(result['resources']); self.assertTrue(all(item['category'] == 'linkedin' for item in result['resources']))
            self.assertEqual(self.client.get('/api/career?q=STAR').json['resources'][0]['id'], 'interview-star')
            for company in self.store.companies(self.owner): self.store.update_company(company['id'], remove=True, user_id=self.owner)
            result = self.client.post('/api/guidance', json={**FORM, 'free_exploration': True}, headers=self.headers)
            self.assertEqual(result.status_code, 200)
            self.assertTrue(any(item['url'] == '/#career' for item in result.json['links']))

    def test_progress_survives_reload_is_private_and_accepts_plain_text(self):
        member, headers, second = self.register('second@example.org')
        progress = {'checklist': ['photo', 'alerts'], 'star': {'question': 'process', 'situation': '<script>plain text</script>', 'task': 'Example'}}
        self.assertEqual(self.client.put('/api/career/progress', json=progress, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get('/api/career').json['progress']['star']['situation'], progress['star']['situation'])
        self.assertEqual(member.get('/api/career').json['progress'], {})
        self.assertEqual(self.store.career_progress(second), {})
        self.assertEqual(Store(self.store.path).career_progress(self.owner)['checklist'], ['photo', 'alerts'])
        self.assertEqual(self.app.test_client().get('/api/career').status_code, 401)

    def test_invalid_progress_and_json_schemas_are_rejected(self):
        for progress in [None, {'checklist': ['other']}, {'star': {'question': 'bad'}}, {'star': {'task': 'x' * 3001}}]:
            self.assertEqual(self.client.put('/api/career/progress', json=progress, headers=self.headers).status_code, 400)
        data = json.loads(Path('resources/career_resources.json').read_text('utf-8'))
        for invalid in ['javascript:alert(1)', 'https://localhost/profile', 'https://secret:password@www.linkedin.com/profile']:
            bad = copy.deepcopy(data); bad['resources'][0]['source_url'] = invalid
            with self.assertRaises(ValueError): career.validate_resources(bad)
        data = json.loads(Path('resources/companies.json').read_text('utf-8')); data['companies'][0]['default_enabled'] = True
        with self.assertRaises(ValueError): catalog.validate_catalog(data)

    def test_discovery_pages_are_relevant_and_do_not_use_ai_by_default(self):
        filters = validate_filters({**FORM, 'country': 'US'}, self.store.companies(self.owner))
        def identify(name, url):
            p, tenant = providers.detect_provider(url)
            return {'name': name, 'url': url, 'provider': p, 'identifier': tenant}
        with patch.object(providers, 'discover_company', side_effect=identify), patch.object(providers, 'fetch_company_jobs', return_value=([], [])) as fetch, patch.object(gemini, 'generate', side_effect=AssertionError('AI')):
            first = discovery.suggest_companies(filters, [])
            second = discovery.suggest_companies(filters, [], offset=first['next_offset'])
        names = [call.args[0]['name'] for call in fetch.call_args_list]
        self.assertEqual(len(names), 10); self.assertEqual(len(set(names)), 10)
        self.assertNotIn('Eli Health', names)
        self.assertEqual(first['companies'], []); self.assertEqual(len(second['reports']), 5)
