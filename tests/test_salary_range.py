"""Faixa salarial opcional e persistência pessoal, sem APIs ou notificações reais."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jobhunter import providers, salary
from web import create_app, validate_filters


class SalaryRangeTests(unittest.TestCase):
    def test_optional_maximum_boundaries_and_published_ranges(self):
        for text, maximum, status in [
            ('BRL 7000 per month', 7000, 'eligible'),
            ('BRL 8000-15000 per month', 10000, 'eligible'),
            ('BRL 15000 per month', 10000, 'above'),
            ('BRL 6000-9000 per month', 10000, 'below'),
            ('BRL 15000 per month', None, 'eligible'),
            ('', 10000, 'review'),
        ]:
            with self.subTest(text=text, maximum=maximum):
                check = salary.evaluate({'salary': text}, maximum=maximum)
                self.assertEqual(check['status'], status)
                self.assertEqual(check['maximum_brl'], maximum)

    def test_maximum_uses_unrounded_converted_monthly_floor(self):
        job = {'salary': 'USD 24000 per year'}
        self.assertEqual(salary.evaluate(job, maximum=10000, rate_fetch=lambda _: (5, '2026-10-12'))['status'], 'eligible')
        self.assertEqual(salary.evaluate(job, maximum=9999, rate_fetch=lambda _: (5, '2026-10-12'))['status'], 'above')

    def test_invalid_ranges_and_legacy_preferences(self):
        form = {'keywords': 'production engineer', 'sources': ['jooble']}
        self.assertIsNone(validate_filters(form, [])['salary_max'])
        for maximum in [True, '10000', '', float('nan'), float('inf'), 6999, 1000001]:
            with self.subTest(maximum=maximum), self.assertRaises(ValueError):
                validate_filters({**form, 'salary_max': maximum}, [])
        self.assertEqual(validate_filters({**form, 'salary_max': 7000}, [])['salary_max'], 7000)
        self.assertEqual(validate_filters({**form, 'profile': 'custom', 'salary_min': 0, 'salary_max': 3000}, [])['salary_max'], 3000)

    def test_provider_excludes_above_maximum_and_preserves_unknown_salary(self):
        jobs = [providers.make_job('Production Engineer', 'Example', 'Curitiba, Brazil', f'https://example.org/{i}', 'QA', country='BR', salary=text)
                for i, text in enumerate(['BRL 8000 per month', 'BRL 12000 per month', '', 'BRL 2600 per month'])]
        form = validate_filters({'keywords': 'production engineer', 'sources': ['companies'], 'company_ids': [1], 'salary_max': 10000}, [{'id': 1, 'enabled': 1}])
        with patch.object(providers, 'fetch_company_jobs', return_value=(jobs, [])):
            result = providers.run_search(form, [{'id': 1, 'enabled': 1, 'name': 'Example', 'provider': 'smartrecruiters', 'identifier': 'Example'}])
        self.assertEqual(len(result['jobs']), 1)
        self.assertEqual(len(result['review_jobs']), 1)
        self.assertEqual(result['reports'][0]['above_maximum'], 1)
        self.assertEqual(result['reports'][0]['below_minimum'], 1)


class PersonalPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'GEMINI_ENABLED': 'false', 'HUNTER_ALLOW_REGISTRATION': 'true'}, clear=True)
        self.env.start()
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name) / 'qa.sqlite')
        self.store = self.app.extensions['store']
        self.client = self.app.test_client()
        csrf = self.client.get('/api/auth/session').json['csrf']
        response = self.client.post('/api/auth/register', headers={'X-Hunter-CSRF': csrf}, json={
            'name': 'QA Father', 'email': 'father@example.org', 'password': 'only-fictitious-password'})
        self.headers = {'X-Hunter-CSRF': response.json['csrf']}
        self.user_id = response.json['user']['id']

    def tearDown(self):
        self.app.extensions['executor'].shutdown(wait=True)
        self.temp.cleanup()
        self.env.stop()

    def test_guided_preferences_persist_and_restore_maximum_optional(self):
        form = {'keywords': 'engenheiro de produto;engenheiro de desenvolvimento de produto', 'profile': 'product',
                'sources': ['jooble'], 'country': 'BR', 'state': 'BR-PR', 'city': 'Curitiba', 'remote': True,
                'salary_min': 8000, 'salary_max': 14000}
        response = self.client.post('/api/preferences', headers=self.headers, json=form)
        self.assertEqual(response.status_code, 200)
        prefs = self.client.get('/api/config').json['preferences']
        self.assertEqual(prefs['keywords'], form['keywords'].split(';'))
        self.assertEqual(prefs['salary_max'], 14000)
        self.assertEqual(prefs['state'], 'BR-PR')
        self.assertTrue(prefs['remote'])
        response = self.client.post('/api/preferences', headers=self.headers, json={**form, 'salary_max': None})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.store.user(self.user_id)['preferences']['salary_max'])

    def test_equivalent_favorites_are_unique_and_can_be_removed_by_either_alias(self):
        aliases = [providers.make_job('Production Engineer', 'Example', 'Curitiba', f'https://example.org/{source}', source, country='BR')
                   for source in ['Jooble', 'Google']]
        for index, job in enumerate(aliases):
            identifier = f'qa-{index}'
            self.store.start_search(identifier, {}, self.user_id)
            self.store.finish_search(identifier, {'jobs': [job]}, user_id=self.user_id)
            response = self.client.post('/api/favorites', headers=self.headers, json={'id': job['id'], 'search_id': identifier})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.store.favorites(self.user_id)), 1)
        response = self.client.delete('/api/favorites/' + aliases[0]['id'], headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.favorites(self.user_id), [])

    def test_notifications_recheck_optional_upper_limit_before_transport(self):
        job = providers.make_job('Production Engineer', 'Example', 'Curitiba', 'https://example.org/above', 'QA', country='BR', salary='BRL 15000 per month')
        form = validate_filters({'keywords': 'production engineer', 'sources': ['jooble'], 'salary_max': 10000}, [])
        self.store.start_search('qa', form, self.user_id)
        self.store.finish_search('qa', {'jobs': [job]}, user_id=self.user_id)
        with patch('main.send_telegram', side_effect=AssertionError('Envio inesperado')):
            response = self.client.post('/api/notify', headers=self.headers, json={'ids': [job['id']], 'search_id': 'qa', 'channels': ['telegram']})
        self.assertEqual(response.status_code, 400)
        self.assertIn('faixa', response.json['error'])


if __name__ == '__main__':
    unittest.main()
