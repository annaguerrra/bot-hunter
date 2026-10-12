"""Autenticação, migração e separação entre contas; sem chamadas externas."""
import json
import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from jobhunter import discovery, gemini, providers
from jobhunter.storage import Store
from web import create_app, validate_filters

PASSWORD = 'a-test-password-long'
FORM = {'keywords': 'product engineer', 'sources': ['companies'], 'profile': 'product'}


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.directory.name) / 'db.sqlite')
        self.app.testing = True
        self.store = self.app.extensions['store']
        self.owner = self.app.test_client()
        self.owner_headers, self.owner_id = self.register(self.owner, 'owner@example.org')

    def tearDown(self):
        self.app.extensions['executor'].shutdown(wait=True)
        self.directory.cleanup()

    def csrf(self, client):
        return {'X-Hunter-CSRF': client.get('/api/auth/session').json['csrf']}

    def register(self, client, email):
        response = client.post('/api/auth/register', headers=self.csrf(client), json={'name': 'Test person', 'email': email, 'password': PASSWORD, 'role': 'admin'})
        self.assertEqual(response.status_code, 201)
        return {'X-Hunter-CSRF': response.json['csrf']}, response.json['user']['id']

    def member(self):
        client = self.app.test_client()
        headers, identifier = self.register(client, 'member@example.org')
        return client, headers, identifier

    def seed_search(self, owner, profile='product', salary='BRL 8000 per month', title='Product Engineer'):
        companies = self.store.companies(owner)
        filters = validate_filters({**FORM, 'profile': profile, 'keywords': title, 'salary_min': 0 if profile == 'custom' else 7000}, companies)
        job = providers.make_job(title, 'Example', 'Berlin, Germany', 'https://example.org/job', 'Example', country='DE', salary=salary)
        identifier = f'search-{owner}'
        self.store.start_search(identifier, filters, owner)
        self.store.finish_search(identifier, {'jobs': [job], 'review_jobs': [], 'search_suggestions': '<p>private</p>'}, user_id=owner)
        return identifier, job

    def test_anonymous_api_is_closed_and_login_page_has_no_private_data(self):
        anon = self.app.test_client()
        for path in ('/api/config', '/api/favorites', '/api/searches', '/api/profile', '/api/search/anything', '/api/search/anything/grounding'):
            self.assertEqual(anon.get(path).status_code, 401)
        self.assertEqual(anon.post('/api/search', json=FORM, headers=self.csrf(anon)).status_code, 401)
        page = anon.get('/').get_data(as_text=True)
        self.assertIn('auth-form', page)
        self.assertNotIn('owner@example.org', page)

    def test_hashes_and_server_assigned_roles(self):
        member, _, identifier = self.member()
        self.assertEqual(member.get('/api/config').json['user']['role'], 'member')
        self.assertEqual(self.store.user(self.owner_id)['role'], 'admin')
        with self.store.connection() as db:
            row = db.execute('SELECT password_hash FROM users WHERE id=?', (identifier,)).fetchone()
        self.assertTrue(row['password_hash'].startswith('scrypt:'))
        self.assertNotIn(PASSWORD, row['password_hash'])
        self.assertNotIn('password_hash', self.owner.get('/api/config').get_data(as_text=True))
        cookies = self.owner.get('/').headers.getlist('Set-Cookie')
        if cookies:
            self.assertIn('HttpOnly', cookies[0])
            self.assertIn('SameSite=Lax', cookies[0])

    def test_other_accounts_cannot_read_or_modify_owner_data(self):
        member, headers, identifier = self.member()
        search_id, job = self.seed_search(self.owner_id)
        self.store.favorite(job, user_id=self.owner_id)
        self.store.mark_delivered([job['id']], 'telegram', self.owner_id)
        self.assertEqual(member.get('/api/search/' + search_id).status_code, 404)
        self.assertEqual(member.get('/api/search/' + search_id + '/grounding').status_code, 404)
        self.assertEqual(member.get('/api/searches').json['searches'], [])
        self.assertEqual(member.get('/api/favorites').json['jobs'], [])
        self.assertFalse(self.store.delivered(job['id'], 'telegram', identifier))
        self.assertEqual(member.post('/api/favorites', json={'id': job['id'], 'search_id': search_id}, headers=headers).status_code, 400)
        company = self.store.companies(self.owner_id)[0]
        self.assertEqual(member.patch(f'/api/companies/{company["id"]}', json={'enabled': False}, headers=headers).status_code, 404)
        self.assertEqual(member.delete(f'/api/companies/{company["id"]}', headers=headers).status_code, 404)
        self.assertEqual(member.post('/api/search', json={**FORM, 'company_ids': [company['id']]}, headers=headers).status_code, 400)
        self.assertEqual(self.store.companies(self.owner_id)[0]['enabled'], 1)
        member.delete('/api/favorites/' + job['id'], headers=headers)
        self.assertEqual(len(self.store.favorites(self.owner_id)), 1)

    def test_member_cannot_change_shared_keys(self):
        member, headers, _ = self.member()
        with patch('jobhunter.configuration.set_key') as save:
            for source in ('gemini', 'google', 'jooble'):
                self.assertEqual(member.post('/api/integrations/' + source, json={'key': 'fake-but-long-enough'}, headers=headers).status_code, 403)
        save.assert_not_called()

    def test_personal_preferences_and_contacts_are_isolated(self):
        member, headers, _ = self.member()
        with patch.dict(os.environ, {'EMAIL_TO': 'private@example.org', 'TELEGRAM_CHAT_ID': '123'}):
            self.assertEqual(member.get('/api/profile').json['contacts'], {})
            response = member.patch('/api/profile', headers=headers, json={'name': 'New name', 'contacts': {'email_to': 'member@example.org', 'telegram_chat_id': '456'}})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.owner.get('/api/profile').json['contacts']['email_to'], 'private@example.org')
        custom = {**FORM, 'profile': 'custom', 'keywords': 'enfermeiro', 'salary_min': 3500}
        self.assertEqual(member.post('/api/preferences', headers=headers, json=custom).status_code, 200)
        self.assertEqual(member.get('/api/config').json['preferences']['keywords'], ['enfermeiro'])
        self.assertEqual(self.owner.get('/api/config').json['preferences'], {})
        for invalid in ({'email_to': 'victim@example.org\r\nBcc: another@example.org'}, {'telegram_chat_id': '@someone'}):
            self.assertEqual(member.patch('/api/profile', json={'contacts': invalid}, headers=headers).status_code, 400)

    def test_notifications_use_only_the_members_destinations(self):
        member, headers, identifier = self.member()
        member.patch('/api/profile', headers=headers, json={'contacts': {'email_to': 'member@example.org', 'telegram_chat_id': '456'}})
        search_id, job = self.seed_search(identifier, 'custom', 'BRL 3500 per month', 'Enfermeiro')
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'fake', 'TELEGRAM_CHAT_ID': 'OWNER_CHAT', 'EMAIL_FROM': 'sender@example.org', 'EMAIL_TO': 'owner@example.org', 'EMAIL_APP_PASSWORD': 'fake'}), patch.object(main, 'send_telegram') as telegram, patch.object(main, 'send_email') as email:
            response = member.post('/api/notify', headers=headers, json={'ids': [job['id']], 'search_id': search_id, 'channels': ['telegram', 'email']})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(report['status'] == 'ok' for report in response.json['reports']))
        self.assertEqual(telegram.call_args.args[1], '456')
        self.assertEqual(email.call_args.args[0]['to'], ['member@example.org'])
        self.assertFalse(self.store.delivered(job['id'], 'telegram', self.owner_id))

    def test_member_without_contacts_cannot_use_owners_transport_destinations(self):
        member, headers, identifier = self.member()
        search_id, job = self.seed_search(identifier)
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'fake', 'TELEGRAM_CHAT_ID': 'OWNER_CHAT'}), patch.object(main, 'send_telegram') as send:
            response = member.post('/api/notify', headers=headers, json={'ids': [job['id']], 'search_id': search_id, 'channels': ['telegram']})
        self.assertEqual(response.json['reports'][0]['status'], 'error')
        send.assert_not_called()

    def test_logout_revokes_replayed_cookie_and_login_rotates_csrf(self):
        cookie = self.owner.get_cookie('hunter_session').value
        old_csrf = self.owner_headers
        self.assertEqual(self.owner.post('/api/auth/logout', headers=old_csrf).status_code, 200)
        self.owner.set_cookie('hunter_session', cookie)
        self.assertEqual(self.owner.get('/api/config').status_code, 401)
        response = self.owner.post('/api/auth/login', headers=self.csrf(self.owner), json={'email': 'OWNER@EXAMPLE.ORG', 'password': PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json['csrf'], old_csrf['X-Hunter-CSRF'])
        self.assertEqual(self.owner.post('/api/preferences', headers=old_csrf, json=FORM).status_code, 403)

    def test_password_change_revokes_other_sessions_and_rejects_old_password(self):
        other = self.app.test_client()
        response = other.post('/api/auth/login', headers=self.csrf(other), json={'email': 'owner@example.org', 'password': PASSWORD})
        self.assertEqual(response.status_code, 200)
        changed = self.owner.post('/api/auth/password', headers=self.owner_headers, json={'password': PASSWORD, 'new_password': 'a-different-password-long'})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(other.get('/api/config').status_code, 401)
        self.assertEqual(self.owner.get('/api/config').status_code, 200)
        failed = other.post('/api/auth/login', headers=self.csrf(other), json={'email': 'owner@example.org', 'password': PASSWORD})
        self.assertEqual(failed.status_code, 401)

    def test_login_limits_and_expired_sessions(self):
        anon = self.app.test_client()
        headers = self.csrf(anon)
        for _ in range(8):
            self.assertEqual(anon.post('/api/auth/login', headers=headers, json={'email': 'owner@example.org', 'password': 'wrong'}).status_code, 401)
        self.assertEqual(anon.post('/api/auth/login', headers=headers, json={'email': 'owner@example.org', 'password': PASSWORD}).status_code, 429)
        with self.store.connection() as db:
            db.execute('UPDATE sessions SET expires=0')
        self.assertEqual(self.owner.get('/api/config').status_code, 401)

    def test_registration_policy_and_password_length(self):
        anon = self.app.test_client()
        with patch.dict(os.environ, {'HUNTER_ALLOW_REGISTRATION': 'false'}):
            self.assertEqual(anon.post('/api/auth/register', headers=self.csrf(anon), json={'email': 'new@example.org', 'name': 'New', 'password': PASSWORD}).status_code, 403)
        self.assertEqual(anon.post('/api/auth/register', headers=self.csrf(anon), json={'email': 'new@example.org', 'name': 'New', 'password': 'short'}).status_code, 400)

    def test_discovery_results_are_private_and_not_search_history(self):
        result = {'kind': 'company_discovery', 'companies': [], 'notes': ['Test'], 'search_suggestions': '<p>Google suggestion</p>'}
        with patch.object(discovery, 'suggest_companies', return_value=result):
            response = self.owner.post('/api/companies/discover', headers=self.owner_headers, json=FORM)
        self.assertEqual(response.status_code, 200)
        identifier = response.json['id']
        self.assertIn('Google suggestion', self.owner.get('/api/search/' + identifier + '/grounding').get_data(as_text=True))
        member, _, _ = self.member()
        self.assertEqual(member.get('/api/search/' + identifier + '/grounding').status_code, 404)
        self.assertEqual(self.owner.get('/api/searches').json['searches'], [])


class MigrationAndDiscoveryTests(unittest.TestCase):
    def test_legacy_data_is_backed_up_and_assigned_only_to_first_account(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.sqlite'
            with sqlite3.connect(path) as db:
                db.executescript("CREATE TABLE companies(id INTEGER PRIMARY KEY,name TEXT,url TEXT UNIQUE,provider TEXT,identifier TEXT,enabled INTEGER); CREATE TABLE searches(id TEXT PRIMARY KEY,filters TEXT,status TEXT,result TEXT,created_at TEXT); CREATE TABLE favorites(id TEXT PRIMARY KEY,payload TEXT); CREATE TABLE deliveries(job_id TEXT,channel TEXT,PRIMARY KEY(job_id,channel));")
                db.execute('INSERT INTO companies VALUES(7,?,?,?,?,1)', ('Bosch', 'https://careers.bosch.com/', 'smartrecruiters', 'BoschGroup'))
                db.execute('INSERT INTO searches VALUES(?,?,?,?,?)', ('old-search', '{}', 'done', '{}', '2026-10-12'))
                db.execute('INSERT INTO favorites VALUES(?,?)', ('old-job', json.dumps({'id': 'old-job'})))
                db.execute('INSERT INTO deliveries VALUES(?,?)', ('old-job', 'email'))
            db.close()
            store = Store(path)
            self.assertTrue(Path(str(path) + '.before-users.bak').exists())
            first = store.register('First', 'first@example.org', PASSWORD)
            second = store.register('Second', 'second@example.org', PASSWORD)
            self.assertEqual(len(store.companies(first['id'])), 5)
            self.assertEqual(next(c['id'] for c in store.companies(first['id']) if c['name'] == 'Bosch'), 7)
            self.assertIsNotNone(store.search('old-search', first['id']))
            self.assertIsNone(store.search('old-search', second['id']))
            self.assertTrue(store.delivered('old-job', 'email', first['id']))
            self.assertFalse(store.delivered('old-job', 'email', second['id']))
            self.assertEqual(store.favorites(second['id']), [])

    def test_discovery_fallback_checks_relevance_and_does_not_trust_uncited_ai_urls(self):
        filters = validate_filters(FORM, [{'id': 1, 'enabled': 1}])
        job = providers.make_job('Product Engineer', 'Example', 'Berlin, Germany', 'https://example.org/1', 'Example', country='DE')
        def identify(name, url):
            provider, tenant = providers.detect_provider(url)
            return {'name': name, 'url': url, 'provider': provider, 'identifier': tenant}
        invented = {'companies': [{'name': 'Invented', 'url': 'https://evil.example/jobs'}]}
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'fake', 'GEMINI_ENABLED': 'true'}), patch.object(gemini, 'generate', return_value=(invented, {})), patch.object(providers, 'discover_company', side_effect=identify) as fetch, patch.dict(providers.COMPANY_PROVIDERS, {'smartrecruiters': lambda c, f: ([job], [])}):
            result = discovery.suggest_companies(filters, [])
        self.assertEqual(len(result['companies']), 5)
        self.assertTrue(all('Product Engineer' == c['evidence'][0]['title'] for c in result['companies']))
        self.assertNotIn('https://evil.example/jobs', [call.args[1] for call in fetch.call_args_list])
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'fake', 'GEMINI_ENABLED': 'true'}), patch.object(gemini, 'generate', side_effect=gemini.GeminiError('HTTP 429')), patch.object(providers, 'discover_company', side_effect=identify), patch.dict(providers.COMPANY_PROVIDERS, {'smartrecruiters': lambda c, f: ([job], [])}):
            result = discovery.suggest_companies({**filters, 'country': 'BR'}, [])
        self.assertEqual(result['companies'], [])
        self.assertIn('429', result['notes'][0])

    def test_custom_gemini_search_respects_non_engineering_profile(self):
        filters = validate_filters({**FORM, 'profile': 'custom', 'keywords': 'enfermeiro', 'salary_min': 3000}, [{'id': 1, 'enabled': 1}])
        with patch.object(gemini, 'generate', return_value=({'pages': []}, {})) as generate:
            gemini.search_jobs(filters)
        prompt = generate.call_args.args[0]
        self.assertIn('enfermeiro', prompt)
        self.assertIn('em qualquer ramo', prompt)


if __name__ == '__main__':
    unittest.main()
