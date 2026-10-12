"""Budget boundaries, caching, isolation and concurrent reservations."""
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch
from jobhunter.usage import UsageBudget, BudgetExceeded
from jobhunter import providers
from web import create_app, validate_filters


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'usage.sqlite'
        self.now = 1791849600.0
        self.budget = UsageBudget(self.path, clock=lambda: self.now)
        self.keys = {'BR': 'test-brazil', 'DE': 'test-germany'}

    def test_user_and_global_limits_stop_before_network_and_survive_restart(self):
        self.budget.set_limits(2, 3, 3)
        self.budget.reserve(1, 'BR', self.keys['BR'])
        self.budget.reserve(1, 'DE', self.keys['DE'])
        with self.assertRaises(BudgetExceeded):
            self.budget.reserve(1, 'BR', self.keys['BR'])
        self.budget.reserve(2, 'BR', self.keys['BR'])
        with self.assertRaises(BudgetExceeded):
            self.budget.reserve(3, 'DE', self.keys['DE'])
        restarted = UsageBudget(self.path, clock=lambda: self.now)
        self.assertEqual(restarted.snapshot(1, self.keys)['used_today'], 2)
        self.assertTrue(restarted.snapshot(2, self.keys)['blocked'])

    def test_concurrent_calls_cannot_overdraw_one_key(self):
        self.budget.set_limits(20, 20, 3)
        def attempt(_):
            try:
                self.budget.reserve(1, 'BR', self.keys['BR'])
                return True
            except BudgetExceeded:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt, range(20))), 3)
        self.assertEqual(self.budget.snapshot(1, self.keys)['used_today'], 3)

    def test_daily_reset_preserves_lifetime_consumption(self):
        self.budget.set_limits(1, 1, 1)
        self.budget.reserve(1, 'BR', self.keys['BR'])
        self.now += 86400
        result = self.budget.snapshot(1, self.keys, admin=True)
        self.assertEqual(result['used_today'], 0)
        self.assertEqual(result['markets'][0]['remaining_estimate'], 499)
        self.budget.reserve(1, 'BR', self.keys['BR'])

    def test_calibrated_lifetime_total_and_same_key_preserve_counts(self):
        self.budget.calibrate('BR', self.keys['BR'], 1)
        self.budget.reserve(1, 'BR', self.keys['BR'])
        with self.assertRaises(BudgetExceeded):
            self.budget.reserve(2, 'BR', self.keys['BR'])
        self.assertEqual(self.budget.snapshot(1, self.keys, True)['markets'][0]['remaining_estimate'], 0)
        new_keys = {'BR': 'new-independent-key'}
        self.assertEqual(self.budget.snapshot(1, new_keys, True)['markets'][0]['remaining_estimate'], 500)

    def test_cache_hit_uses_no_call_even_when_daily_limit_is_exhausted(self):
        self.budget.set_limits(1, 1, 1)
        filters = validate_filters({'keywords': 'product engineer', 'country': 'BR', 'sources': ['jooble'], 'multilingual': False}, [])
        response = Mock(status_code=200)
        response.json.return_value = {'jobs': []}
        with patch.dict(os.environ, {'JOOBLE_API_KEY': '', 'JOOBLE_API_KEY_BR': self.keys['BR']}, clear=True), patch.object(providers.requests, 'post', return_value=response) as send:
            providers.jooble(filters, self.budget, 1)
            _, notes = providers.jooble(filters, self.budget, 1)
            self.assertEqual(send.call_count, 1)
            self.assertTrue(any('cache' in note for note in notes))
        self.assertEqual(self.budget.snapshot(1, self.keys)['used_today'], 1)

    def test_cache_expires_and_query_changes_require_new_reservation(self):
        self.budget.remember('key', {'keywords': 'a'}, [])
        self.assertEqual(self.budget.cached('key', {'keywords': 'a'}), [])
        self.assertIsNone(self.budget.cached('key', {'keywords': 'b'}))
        self.now += 86401
        self.assertIsNone(self.budget.cached('key', {'keywords': 'a'}))

    def test_rotation_respects_candidates_and_blocked_keys(self):
        self.budget.reserve(1, 'BR', self.keys['BR'])
        self.assertEqual(self.budget.rank_markets(1, ['BR', 'DE'], self.keys), ['DE', 'BR'])
        self.budget.block(self.keys['DE'])
        self.assertEqual(self.budget.rank_markets(1, ['BR', 'DE'], self.keys), ['BR', 'DE'])
        self.assertEqual(self.budget.rank_markets(1, ['DE'], self.keys), ['DE'])

    def test_member_usage_and_guidance_make_no_provider_calls(self):
        app = create_app(self.path)
        self.addCleanup(app.extensions['executor'].shutdown, wait=True)
        client = app.test_client()
        csrf = client.get('/api/auth/session').json['csrf']
        result = client.post('/api/auth/register', json={'name': 'Owner', 'email': 'owner@example.org', 'password': 'long-test-password'}, headers={'X-Hunter-CSRF': csrf})
        member = app.test_client()
        csrf = member.get('/api/auth/session').json['csrf']
        result = member.post('/api/auth/register', json={'name': 'Father', 'email': 'father@example.org', 'password': 'long-test-password'}, headers={'X-Hunter-CSRF': csrf})
        headers = {'X-Hunter-CSRF': result.json['csrf']}
        self.assertNotIn('markets', member.get('/api/usage').json)
        self.assertNotIn('users', member.get('/api/usage').json)
        self.assertEqual(member.post('/api/integrations/usage', json={'user_daily': 500}, headers=headers).status_code, 403)
        with patch.object(providers.requests, 'get') as get, patch.object(providers.requests, 'post') as post:
            result = member.post('/api/guidance', json={'keywords': 'product engineer', 'sources': ['companies']}, headers=headers)
            self.assertEqual(result.status_code, 200)
            self.assertTrue(any('linkedin.com' in link['url'] for link in result.json['links']))
            get.assert_not_called();post.assert_not_called()

    def test_denied_budget_makes_no_network_call(self):
        self.budget.calibrate('BR', self.keys['BR'], 0)
        filters = validate_filters({'keywords': 'product engineer', 'country': 'BR', 'sources': ['jooble'], 'multilingual': False}, [])
        with patch.dict(os.environ, {'JOOBLE_API_KEY': '', 'JOOBLE_API_KEY_BR': self.keys['BR']}, clear=True), patch.object(providers.requests, 'post') as send:
            jobs, notes = providers.jooble(filters, self.budget, 1)
            self.assertEqual(jobs, [])
            send.assert_not_called()
            self.assertTrue(any('500' in note for note in notes))

    def test_member_override_and_key_alias_share_global_consumption(self):
        self.budget.set_limits(1, 10, 5, user_id=2)
        self.budget.reserve(2, 'BR', self.keys['BR'])
        with self.assertRaises(BudgetExceeded):
            self.budget.reserve(2, 'DE', self.keys['DE'])
        self.assertEqual(self.budget.snapshot(1, self.keys)['limits']['user_daily'], 12)
        self.assertEqual(self.budget.snapshot(2, self.keys)['limits']['user_daily'], 1)
        self.assertNotIn(self.keys['BR'], str(self.budget.snapshot(1, self.keys, True)))


if __name__ == '__main__':
    unittest.main()
