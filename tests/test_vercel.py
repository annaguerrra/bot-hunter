"""Contratos do ambiente público, sem consultas nem notificações reais."""
import importlib.util
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import main
from jobhunter import http, providers
from jobhunter.storage import Store
from jobhunter.usage import UsageBudget
from scripts.build_vercel import build
from web import create_app, validate_filters

BASE = Path(__file__).resolve().parents[1]
FORM = {'keywords': 'production engineer', 'sources': ['companies'], 'company_ids': [1]}


def job(number=1):
    return providers.make_job('Production Engineer', 'Example', 'Curitiba, Brazil',
                              f'https://example.org/jobs/{number}', 'Example',
                              country='BR', salary='BRL 8,000 per month')


class DeadlineTests(unittest.TestCase):
    def test_expiration_blocks_network_and_context_is_reset(self):
        with patch.object(http.requests, 'get') as network:
            with http.deadline(-1), self.assertRaises(http.SearchDeadlineExceeded):
                http.get('https://example.org', timeout=25)
            network.assert_not_called()
            http.get('https://example.org', timeout=25)
            self.assertEqual(network.call_args.kwargs['timeout'], 25)

    def test_network_timeouts_fit_remaining_budget(self):
        with patch.object(http.requests, 'post') as network, http.deadline(10):
            http.post('https://example.org', timeout=90)
        connect, read = network.call_args.kwargs['timeout']
        self.assertLess(connect + read, 10)
        self.assertGreater(connect, 0)

    def test_completed_source_survives_deadline_in_next_source(self):
        companies = [{'id': 1, 'name': 'First', 'enabled': 1, 'provider': 'test'},
                     {'id': 2, 'name': 'Second', 'enabled': 1, 'provider': 'test'}]
        filters = validate_filters({**FORM, 'company_ids': [1, 2]}, companies)
        def fetch(company, query):
            if company['id'] == 2:
                raise http.SearchDeadlineExceeded()
            return [job()], []
        with patch.dict(providers.COMPANY_PROVIDERS, {'test': fetch}), patch.object(providers, 'enrich_company_jobs', side_effect=lambda company, jobs, filters: (jobs, [])):
            result = providers.run_search(filters, companies)
        self.assertTrue(result['time_limited'])
        self.assertEqual(len(result['jobs']), 1)
        self.assertEqual(result['reports'][-1]['status'], 'limited')

    def test_expired_search_does_not_reserve_provider_quota(self):
        filters = {'country': 'BR', 'region': '', 'city': '', 'state': '', 'keywords': ['engineer'], 'pages': 1}
        usage = MagicMock()
        usage.cached.return_value = None
        with patch.dict(os.environ, {'SERPAPI_API_KEY': 'fake-serp-key'}), http.deadline(-1), self.assertRaises(http.SearchDeadlineExceeded):
            providers.google_jobs(filters, usage)
        usage.reserve.assert_not_called()
        usage.cached.assert_called_once()


class ServerlessTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'HUNTER_SERVERLESS': 'true', 'HUNTER_HTTPS': 'false',
            'HUNTER_ALLOW_REGISTRATION': 'true', 'DATABASE_URL': '', 'EMAIL_DELIVERY_MODE': 'queue',
            'EMAIL_FROM': 'qa@example.org', 'EMAIL_APP_PASSWORD': 'qa-password', 'TELEGRAM_BOT_TOKEN': 'qa-token'}, clear=True)
        self.environment.start()
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'hunter.sqlite'
        self.app = create_app(self.path)
        self.client = self.app.test_client()
        page = self.client.get('/').get_data(as_text=True)
        csrf = re.search(r'name="hunter-csrf" content="([^"]+)"', page).group(1)
        response = self.client.post('/api/auth/register', json={'name': 'QA', 'email': 'qa@example.org', 'password': 'qa-test-password-long'}, headers={'X-Hunter-CSRF': csrf})
        self.assertEqual(response.status_code, 201)
        self.owner = response.json['user']['id']
        self.headers = {'X-Hunter-CSRF': response.json['csrf']}
        self.store = self.app.extensions['store']
        self.store.update_user(self.owner, contacts={'email_to': 'target@example.org', 'telegram_chat_id': '123'})

    def tearDown(self):
        self.app.extensions['executor'].shutdown(wait=True)
        self.directory.cleanup()
        self.environment.stop()

    def search(self, jobs=None):
        with patch.object(providers, 'run_search', return_value={'jobs': jobs or [job()], 'reports': []}), patch.object(self.app.extensions['executor'], 'submit') as background:
            response = self.client.post('/api/search', json=FORM, headers=self.headers)
        self.assertEqual(response.status_code, 202)
        background.assert_not_called()
        self.assertEqual(self.store.search(response.json['id'], self.owner)['status'], 'done')
        return response.json['id']

    def test_search_is_persisted_before_http_response(self):
        self.search()

    def test_cold_start_preserves_active_search_and_session(self):
        self.store.start_search('active', {}, self.owner)
        second = create_app(self.path)
        try:
            self.assertEqual(second.extensions['store'].search('active', self.owner)['status'], 'running')
            with self.client.session_transaction() as session:
                token = session['token']
            self.assertEqual(second.extensions['store'].session_user(token)['id'], self.owner)
            self.assertEqual(second.secret_key, self.app.secret_key)
        finally:
            second.extensions['executor'].shutdown(wait=True)

    def test_only_stale_searches_of_current_user_are_expired(self):
        self.store.start_search('stale', {}, self.owner)
        self.store.start_search('other', {}, 999)
        self.store.start_search('active', {}, self.owner)
        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        with self.store.connection() as db:
            db.execute('UPDATE searches SET created_at=? WHERE id IN (?,?)', (old, 'stale', 'other'))
        self.assertEqual(self.client.get('/api/search/stale').json['status'], 'interrupted')
        self.assertEqual(self.store.search('other', 999)['status'], 'running')
        self.assertEqual(self.store.search('active', self.owner)['status'], 'running')

    def test_email_is_queued_once_without_smtp_in_function(self):
        identifier = self.search()
        stored = self.store.search(identifier, self.owner)['jobs'][0]
        body = {'ids': [stored['id']], 'search_id': identifier, 'channels': ['email']}
        with patch.object(main, 'send_email') as smtp:
            first = self.client.post('/api/notify', json=body, headers=self.headers)
            second = self.client.post('/api/notify', json=body, headers=self.headers)
        smtp.assert_not_called()
        self.assertEqual(first.json['reports'][0]['status'], 'queued')
        self.assertEqual(first.json['reports'][0]['queued'], 1)
        self.assertEqual(second.json['reports'][0]['queued'], 0)
        self.assertEqual(len(self.client.get('/api/email-queue').json['batches']), 1)

    def test_telegram_batches_are_bounded_and_confirmed_individually(self):
        identifier = self.search()
        stored = self.store.search(identifier, self.owner)['jobs'][0]
        body = {'ids': [stored['id']], 'search_id': identifier, 'channels': ['telegram']}
        self.assertEqual(self.client.get('/api/config').json['limits']['telegram_batch_jobs'], 1)
        with patch.object(main, 'send_telegram') as telegram:
            invalid = self.client.post('/api/notify', json={**body, 'ids': [stored['id'], 'other']}, headers=self.headers)
            self.assertEqual(invalid.status_code, 400)
            telegram.assert_not_called()
            self.assertEqual(self.client.post('/api/notify', json=body, headers=self.headers).json['reports'][0]['sent'], 1)
            self.assertEqual(self.client.post('/api/notify', json=body, headers=self.headers).json['reports'][0]['sent'], 0)
        telegram.assert_called_once()

    def test_vercel_domains_are_allowed_and_https_cookie_is_secure(self):
        with patch.dict(os.environ, {'VERCEL': '1', 'VERCEL_URL': 'hunter-preview.vercel.app',
                'VERCEL_PROJECT_PRODUCTION_URL': 'hunter.vercel.app', 'HUNTER_HTTPS': 'true'}):
            second = create_app(self.path)
        try:
            client = second.test_client()
            response = client.get('/', base_url='https://hunter.vercel.app')
            self.assertEqual(response.status_code, 200)
            cookie = response.headers['Set-Cookie']
            self.assertIn('Secure', cookie)
            self.assertIn('HttpOnly', cookie)
            self.assertEqual(client.get('/', base_url='https://hunter-preview.vercel.app').status_code, 200)
            self.assertEqual(client.get('/', base_url='https://other.vercel.app').status_code, 400)
        finally:
            second.extensions['executor'].shutdown(wait=True)


class DeploymentTests(unittest.TestCase):
    def test_postgres_initialization_does_not_write_to_function_filesystem(self):
        with patch.object(Path, 'mkdir', side_effect=AssertionError('read-only')), patch('jobhunter.storage.connection'), patch('jobhunter.usage.connection'):
            Store('/readonly/data/hunter.sqlite', 'postgresql://qa.invalid/db', recover_searches=False)
            UsageBudget('/readonly/data/hunter.sqlite', 'postgresql://qa.invalid/db')

    def test_public_build_copies_assets_without_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name in ('static', 'assets'):
                (base / name).mkdir()
                (base / name / 'qa.txt').write_text('public')
            (base / '.env').write_text('DATABASE_URL=private')
            build(base)
            self.assertTrue((base / 'public/static/qa.txt').is_file())
            self.assertEqual({p.relative_to(base / 'public').as_posix() for p in (base / 'public').rglob('*') if p.is_file()}, {'static/qa.txt', 'assets/qa.txt'})

    def test_explicit_entrypoint_preserves_bot_cli(self):
        import tomllib
        config = tomllib.loads((BASE / 'pyproject.toml').read_text(encoding='utf-8'))
        self.assertEqual(config['tool']['vercel']['entrypoint'], 'app:app')
        self.assertIn('app.py', json.loads((BASE / 'vercel.json').read_text())['functions'])
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(RuntimeError, 'DATABASE_URL'):
            spec = importlib.util.spec_from_file_location('qa_vercel_entry', BASE / 'app.py')
            spec.loader.exec_module(importlib.util.module_from_spec(spec))


if __name__ == '__main__':
    unittest.main()
