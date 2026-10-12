"""Testes do guia inicial, cotas Google, identidade persistente e fila de e-mails."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, parse_qs
import requests
import main
from jobhunter.email_queue import EmailQueue
from jobhunter.google_usage import GoogleBudget
from jobhunter.usage import UsageBudget, BudgetExceeded
from jobhunter import gemini, providers
from jobhunter.storage import Store
from web import create_app, validate_filters


class OnboardingCloudTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'HUNTER_SETUP_TOKEN': '', 'HUNTER_ALLOW_REGISTRATION': 'true', 'DATABASE_URL': '', 'EMAIL_DELIVERY_MODE': 'direct', 'GEMINI_ENABLED': 'true', 'SERPAPI_DAILY_LIMIT': '3', 'SERPAPI_MONTHLY_LIMIT': '250'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'test.sqlite'
        self.app = create_app(self.path)
        self.addCleanup(self.app.extensions['executor'].shutdown, wait=True)
        self.store = self.app.extensions['store']
        self.owner, self.owner_headers, self.owner_id = self.register('owner@example.org')
        self.member, self.headers, self.member_id = self.register('member@example.org')

    def register(self, email):
        client = self.app.test_client()
        csrf = client.get('/api/auth/session').json['csrf']
        response = client.post('/api/auth/register', headers={'X-Hunter-CSRF': csrf}, json={'name': 'Test user', 'email': email, 'password': 'a-long-fake-password'})
        self.assertEqual(response.status_code, 201)
        return client, {'X-Hunter-CSRF': response.json['csrf']}, response.json['user']['id']

    def test_tour_is_private_persistent_and_does_not_require_contacts(self):
        self.assertEqual(self.member.get('/api/onboarding').json['tour_status'], 'new')
        result = self.member.post('/api/onboarding', headers=self.headers, json={'tour_status':'paused','tour_step':4,'user_id':self.owner_id})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.owner.get('/api/onboarding').json['tour_status'], 'new')
        restarted = Store(self.path)
        self.assertEqual(json.loads(restarted.setting(f'onboarding:{self.member_id}'))['tour_step'], 4)
        self.assertEqual(self.member.post('/api/onboarding', headers=self.headers, json={'tour_status':'completed','tour_step':9}).status_code, 200)
        self.assertEqual(self.member.get('/api/onboarding').json['tour_status'], 'completed')
        self.assertEqual(self.member.get('/api/onboarding').json['checklist'], {'email':False,'telegram':False,'preferences':False})
        self.assertEqual(self.member.post('/api/onboarding', headers=self.headers, json={'tour_status':'completed','tour_step':100}).status_code, 400)
        self.assertEqual(self.member.post('/api/onboarding', json={'tour_status':'completed','tour_step':1}).status_code, 403)

    def test_telegram_link_matches_only_private_nonce_and_preserves_email(self):
        self.store.update_user(self.member_id, contacts={'email_to':'member-alerts@example.org'})
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN':'fake-test-token'}), patch('jobhunter.onboarding.requests.get') as get:
            get.return_value = Mock(status_code=200, json=lambda:{'ok':True,'result':{'username':'hunter_test_bot'}})
            response = self.member.post('/api/onboarding/telegram', headers=self.headers, json={})
            nonce = parse_qs(urlsplit(response.json['url']).query)['start'][0]
            self.assertNotIn('fake-test-token', response.get_data(as_text=True))
            self.assertEqual(self.owner.post('/api/onboarding/telegram/confirm', headers=self.owner_headers, json={}).status_code, 400)
            updates = [ {'message': {'text':'/start other_nonce', 'chat':{'id':123,'type':'private'}, 'from':{'id':123}, 'date':int(time.time())}},
                        {'message': {'text':'/start '+nonce, 'chat':{'id':456,'type':'group'}, 'from':{'id':456}, 'date':int(time.time())}} ]
            get.return_value = Mock(status_code=200, json=lambda:{'ok':True,'result':updates})
            self.assertTrue(self.member.post('/api/onboarding/telegram/confirm', headers=self.headers, json={}).json['pending'])
            updates.append({'message': {'text':'/start '+nonce, 'chat':{'id':789,'type':'private'}, 'from':{'id':789}, 'date':int(time.time())}})
            result = self.member.post('/api/onboarding/telegram/confirm', headers=self.headers, json={})
            self.assertEqual(result.json['chat_id'], '789')
            self.assertEqual(self.store.user(self.member_id)['contacts'], {'email_to':'member-alerts@example.org','telegram_chat_id':'789'})
            self.assertEqual(self.member.post('/api/onboarding/telegram/confirm', headers=self.headers, json={}).status_code, 400)
            self.assertNotIn('offset', get.call_args.kwargs['params'])

    def test_google_daily_cache_and_monthly_reset_are_shared(self):
        usage = UsageBudget(self.path, clock=lambda: self.now)
        self.now = 1791849600.0
        budget = GoogleBudget(usage)
        budget.configure(3, 4)
        for _ in range(3): budget.reserve()
        with self.assertRaises(BudgetExceeded): budget.reserve()
        self.now += 86400
        budget.reserve()
        with self.assertRaises(BudgetExceeded): budget.reserve()
        self.now += 32 * 86400
        budget.reserve()
        self.assertEqual(budget.snapshot()['used_month'], 1)

    def test_google_provider_reserves_only_real_calls_and_hides_errors(self):
        usage = self.app.extensions['usage']
        form = validate_filters({'keywords':'product engineer','sources':['google'],'profile':'product','country':'BR','pages':1}, self.store.companies(self.member_id))
        response = Mock(status_code=200, json=lambda:{'jobs_results':[{'title':'Product Engineer','company_name':'Example','location':'Curitiba, PR','detected_extensions':{'salary':'R$ 8.000 mensal'},'apply_options':[{'link':'https://example.org/vaga'}]}]})
        with patch.dict(os.environ, {'SERPAPI_API_KEY':'fake-serp-key'}), patch.object(providers.requests, 'get', return_value=response) as get:
            jobs, _ = providers.google_jobs(form, usage, self.member_id)
            self.assertEqual(jobs[0]['source'], 'Google Empregos')
            self.assertEqual(get.call_args.kwargs['params']['engine'], 'google_jobs')
            providers.google_jobs(form, usage, self.owner_id)
            self.assertEqual(get.call_count, 1)
            self.assertEqual(GoogleBudget(usage).snapshot()['used_month'], 1)
            get.side_effect = requests.Timeout('contains-private-key')
            jobs, notes = providers.google_jobs({**form,'keywords':['different-query']}, usage, self.member_id)
            self.assertEqual(jobs, [])
            self.assertNotIn('contains-private-key', ' '.join(notes))
            self.assertEqual(GoogleBudget(usage).snapshot()['used_month'], 2)

    def test_job_identity_survives_source_changes_restart_and_accounts(self):
        first = providers.make_job('Product Engineer','Example','Curitiba, PR','https://jooble.org/a','Jooble',salary='R$ 8000 mensal')
        second = providers.make_job('PRODUCT ENGINEER','Example','Curitiba, PR','https://example.org/b','Google Empregos',salary='R$ 8000 mensal')
        for search, job in [('first',first),('second',second)]:
            self.store.start_search(search, {}, self.member_id)
            self.store.finish_search(search, {'jobs':[job]}, user_id=self.member_id)
        self.store.mark_delivered([first['id']], 'email', self.member_id)
        self.assertTrue(Store(self.path).delivered(second['id'], 'email', self.member_id))
        self.assertFalse(self.store.delivered(second['id'], 'telegram', self.member_id))
        self.assertFalse(self.store.delivered(second['id'], 'email', self.owner_id))
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) AS count FROM job_index WHERE user_id=?',(self.member_id,)).fetchone()['count'],1)

    def test_email_queue_is_private_deduplicated_and_marks_only_confirmed_delivery(self):
        job = providers.make_job('Product Engineer','Example','Berlin','https://example.org/job','Jooble',salary='BRL 8000 per month')
        self.store.start_search('email', {}, self.member_id)
        self.store.finish_search('email', {'jobs':[job]}, user_id=self.member_id)
        queue = EmailQueue(self.store)
        self.assertEqual(queue.enqueue(self.member_id, 'member@example.org', [job]), 1)
        self.assertEqual(queue.enqueue(self.member_id, 'member@example.org', [job]), 0)
        self.assertFalse(self.store.delivered(job['id'], 'email', self.member_id))
        self.assertEqual(self.owner.get('/api/email-queue').json['batches'], [])
        sender = Mock(side_effect=RuntimeError('private-credential'))
        self.assertEqual(queue.process(sender)['failed_batches'], 1)
        batch = queue.status(self.member_id)[0]
        self.assertEqual(self.owner.post(f'/api/email-queue/{batch["id"]}/retry',headers=self.owner_headers,json={}).status_code,400)
        self.assertTrue(queue.retry(batch['id'], self.member_id))
        sender.side_effect = None
        self.assertEqual(queue.process(sender)['sent_jobs'], 1)
        self.assertTrue(self.store.delivered(job['id'], 'email', self.member_id))
        self.assertEqual(queue.enqueue(self.member_id, 'member@example.org', [job]), 0)

    def test_optional_gemini_does_not_contact_api(self):
        with patch.dict(os.environ, {'GEMINI_ENABLED':'false','GEMINI_API_KEY':'fake-key'}), patch.object(gemini.requests,'post') as post:
            with self.assertRaises(gemini.GeminiError): gemini.generate('test')
            post.assert_not_called()

    def test_setup_updates_one_contact_without_overwriting_the_other(self):
        self.member.patch('/api/profile', headers=self.headers, json={'contacts':{'email_to':'father@example.org'}})
        self.member.patch('/api/profile', headers=self.headers, json={'contacts':{'telegram_chat_id':'12345'}})
        self.assertEqual(self.store.user(self.member_id)['contacts'], {'email_to':'father@example.org','telegram_chat_id':'12345'})

    def test_empty_google_results_are_cached_without_quota_pause(self):
        usage = self.app.extensions['usage']
        form = validate_filters({'keywords':'empty-query','sources':['google'],'country':'BR','pages':1}, [])
        response = Mock(status_code=200, json=lambda:{'error':"Google hasn't returned any results for this query."})
        with patch.dict(os.environ, {'SERPAPI_API_KEY':'fake-serp-empty'}), patch.object(providers.requests, 'get', return_value=response) as get:
            self.assertEqual(providers.google_jobs(form, usage, self.member_id)[0], [])
            self.assertEqual(providers.google_jobs(form, usage, self.owner_id)[0], [])
            self.assertEqual(get.call_count, 1)
            self.assertEqual(GoogleBudget(usage).snapshot()['blocked_until'], 0)

    def test_uncertain_email_is_not_automatically_retried(self):
        job = providers.make_job('Product Engineer','Example','Berlin','https://example.org/pending','Jooble')
        queue = EmailQueue(self.store)
        queue.enqueue(self.member_id, 'member@example.org', [job])
        with self.store.connection() as db:
            db.execute("UPDATE email_outbox SET status='sending',attempts=1,lease=?", (time.time()-1,))
        sender = Mock()
        queue.process(sender)
        sender.assert_not_called()
        batch = queue.status(self.member_id)[0]
        self.assertEqual(batch['status'], 'uncertain')
        self.assertTrue(queue.retry(batch['id'], self.member_id))
        self.assertEqual(queue.process(sender)['sent_jobs'], 1)

    def test_automation_accepts_saved_preferences_and_sends_both_channels(self):
        from scripts import cloud_alerts
        form = validate_filters({'keywords':'product engineer','profile':'product','country':'BR','salary_min':7000,'sources':['jooble','google']}, [])
        self.store.update_user(self.owner_id, contacts={'email_to':'', 'telegram_chat_id':''})
        self.store.update_user(self.member_id, preferences=form, contacts={'email_to':'member@example.org','telegram_chat_id':'12345'})
        job = providers.make_job('Product Engineer','Example','Curitiba, PR','https://example.org/automated','Jooble',salary='R$ 8000 mensal')
        with patch.dict(os.environ, {'SEND_EMAIL':'true','SEND_TELEGRAM':'true','SERPAPI_API_KEY':'fake-serp','GEMINI_ENABLED':'false'}), patch.object(cloud_alerts,'Store',return_value=self.store), patch.object(cloud_alerts,'UsageBudget',return_value=self.app.extensions['usage']), patch.object(cloud_alerts,'load_settings'), patch.object(main,'required_env',return_value='fake-token'), patch.object(main,'email_settings',return_value={'sender':'fake'}), patch.object(main,'send_email') as email, patch.object(main,'send_telegram') as telegram, patch.object(providers,'jooble_keys',return_value={'BR':'fake-key'}), patch.object(providers,'run_search',return_value={'jobs':[job]}) as search:
            cloud_alerts.run(search=True)
            self.assertEqual(search.call_args.args[0]['keywords'], ['product engineer'])
            self.assertEqual(search.call_args.kwargs['user_id'], self.member_id)
            email.assert_called_once()
            telegram.assert_called_once()
            self.assertTrue(self.store.delivered(job['id'], 'email', self.member_id))
            self.assertTrue(self.store.delivered(job['id'], 'telegram', self.member_id))

    def test_workflow_keeps_weekday_schedule_and_optional_gemini(self):
        import yaml
        workflow = yaml.load((Path(__file__).resolve().parents[1] / '.github/workflows/job-alerts.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
        self.assertEqual(workflow['on']['schedule'], [{'cron': '17 9 * * 1-5', 'timezone': 'America/Sao_Paulo'}])
        self.assertIn('workflow_dispatch', workflow['on'])
        env = workflow['jobs']['send-jobs']['steps'][-1]['env']
        self.assertEqual(env['DATABASE_URL'], '${{ secrets.DATABASE_URL }}')
        self.assertEqual(env['EMAIL_PROVIDER'], 'smtp')
        self.assertIn("'false'", env['GEMINI_ENABLED'])
        self.assertIn('JOOBLE_KEYS_JSON', env)
        self.assertIn('secrets.TELEGRAM_BOT_TOKEN', env['TELEGRAM_BOT_TOKEN'])


if __name__ == '__main__': unittest.main()
