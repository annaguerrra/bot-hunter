"""Histórico, catálogo deduplicado e isolamento; nenhuma consulta externa."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import requests
from jobhunter import providers, salary, matching
from web import create_app


class HistoryCatalogTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'GEMINI_ENABLED': 'false', 'HUNTER_ALLOW_REGISTRATION': 'true'}, clear=True)
        self.env.start()
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name) / 'test.sqlite')
        self.store = self.app.extensions['store']
        self.owner, self.member = self.app.test_client(), self.app.test_client()
        self.owner_headers, self.owner_id = self.register(self.owner, 'owner@example.org')
        self.member_headers, self.member_id = self.register(self.member, 'member@example.org')
        for method in ('get', 'post'):
            guard = patch.object(requests, method, side_effect=AssertionError('Consulta externa inesperada'))
            guard.start(); self.addCleanup(guard.stop)

    def tearDown(self):
        self.app.extensions['executor'].shutdown(wait=True)
        self.temp.cleanup(); self.env.stop()

    def register(self, client, email):
        csrf = client.get('/api/auth/session').json['csrf']
        result = client.post('/api/auth/register', headers={'X-Hunter-CSRF': csrf}, json={'name': 'QA', 'email': email, 'password': 'strong-password-test'})
        self.assertEqual(result.status_code, 201)
        return {'X-Hunter-CSRF': result.json['csrf']}, result.json['user']['id']

    def job(self, number=0, source='Jooble', pay='BRL 8,000 per month'):
        job = providers.make_job('Product Engineer', f'Example {number}', 'Berlin', f'https://example.org/{source}/{number}', source, salary=pay, country='DE', description='Verified description ' * 100)
        job['match'] = matching.assess(job, 'product', ['product engineer'], True, [])
        job['salary_check'] = salary.evaluate(job, 7000)
        return job

    def save(self, identifier, jobs, review=None, user=None):
        user = self.owner_id if user is None else user
        self.store.start_search(identifier, {'keywords': ['product engineer'], 'country': 'DE'}, user)
        self.store.finish_search(identifier, {'jobs': jobs, 'review_jobs': review or []}, user_id=user)

    def test_history_counts_and_short_previews_preserve_search_snapshots(self):
        jobs = [self.job(index) for index in range(4)]
        self.save('first', jobs, [self.job(8, pay='')])
        result = self.owner.get('/api/searches').json['searches'][0]
        self.assertEqual((result['jobs_count'], result['review_count']), (4, 1))
        self.assertEqual(len(result['preview_jobs']), 3)
        self.assertNotIn('description', result['preview_jobs'][0])
        full = self.owner.get('/api/search/first').json
        self.assertEqual(len(full['jobs']), 4)
        self.assertEqual(full['jobs'][0]['description'], jobs[0]['description'])

    def test_catalog_combines_sources_but_history_keeps_original_results(self):
        first, second = self.job(), self.job(source='Google Empregos')
        self.save('first', [first]); self.save('second', [second])
        result = self.owner.get('/api/jobs').json
        self.assertEqual(result['total'], 1)
        self.assertEqual(set(result['jobs'][0]['sources']), {'Jooble', 'Google Empregos'})
        self.assertEqual(self.owner.get('/api/search/first').json['jobs'][0]['id'], first['id'])

    def test_catalog_covers_older_searches_with_pagination_and_salary_filter(self):
        for index in range(42): self.save(f'search-{index}', [self.job(index)])
        self.save('review', [], [self.job(100, pay='')])
        self.assertEqual(len(self.owner.get('/api/searches').json['searches']), 20)
        first = self.owner.get('/api/jobs').json
        second = self.owner.get('/api/jobs?offset=40').json
        self.assertEqual((first['total'], len(first['jobs']), len(second['jobs'])), (43, 40, 3))
        self.assertFalse({j['canonical_id'] for j in first['jobs']} & {j['canonical_id'] for j in second['jobs']})
        self.assertEqual(self.owner.get('/api/jobs?status=review').json['total'], 1)
        self.assertEqual(self.owner.get('/api/jobs?status=eligible').json['total'], 42)

    def test_catalog_and_previews_are_private_and_save_uses_owned_index(self):
        owned, foreign = self.job(), self.job(2)
        self.save('owned', [owned]); self.save('foreign', [foreign], user=self.member_id)
        self.assertEqual(self.app.test_client().get('/api/jobs').status_code, 401)
        self.assertEqual(self.owner.get('/api/jobs').json['total'], 1)
        self.assertNotIn('Example 2', str(self.owner.get('/api/searches').json))
        response = self.owner.post('/api/favorites', headers=self.owner_headers, json={'id': owned['id']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.member.post('/api/favorites', headers=self.member_headers, json={'id': owned['id']}).status_code, 400)
        self.assertEqual(self.store.indexed_job(owned['id'], self.member_id), None)

    def test_invalid_filters_and_pages_are_rejected(self):
        for query in ('offset=-1', 'offset=no', 'offset=900000', 'status=anything'):
            self.assertEqual(self.owner.get('/api/jobs?' + query).status_code, 400)
        for identifier in (None, {}, [], 123):
            self.assertEqual(self.owner.post('/api/favorites', headers=self.owner_headers, json={'id': identifier}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
