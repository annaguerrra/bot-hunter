"""Lotes maiores, cota de busca e limites Telegram, sem envios externos."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
import main
from jobhunter import providers
from jobhunter.delivery import TelegramPacer
from web import create_app, validate_filters


class DeliveryLimitsTests(unittest.TestCase):
    def test_pacer_spaces_private_and_group_messages_without_real_sleep(self):
        now = [100.0]
        waits, sends = [], []
        def sleep(seconds):
            waits.append(seconds)
            now[0] += seconds
        pacer = TelegramPacer(clock=lambda: now[0], sleep=sleep)
        send = lambda token, chat, message: sends.append((chat, message))
        pacer.send(send, 'secret', '123', 'First')
        pacer.send(send, 'secret', '123', 'Second')
        pacer.send(send, 'secret', '-456', 'Group first')
        pacer.send(send, 'secret', '-456', 'Group second')
        self.assertAlmostEqual(waits[0], 1.1)
        self.assertAlmostEqual(waits[1], 3.1)
        self.assertEqual(len(sends), 4)
        self.assertNotIn('secret', repr(pacer.last))

    def test_retry_after_is_respected_and_never_retries_ambiguous_timeout(self):
        first, second = requests.Response(), requests.Response()
        first.status_code = 429
        first._content = b'{"ok":false,"parameters":{"retry_after":2}}'
        second.status_code = 200
        second._content = b'{"ok":true}'
        with patch.object(requests, 'post', side_effect=[first, second]) as post, patch.object(main.time, 'sleep') as sleep:
            main.send_telegram('secret', '123', 'Hello')
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(2)
        with patch.object(requests, 'post', side_effect=requests.Timeout('secret-in-url')) as post:
            with self.assertRaisesRegex(RuntimeError, 'Timeout') as error:
                main.send_telegram('secret', '123', 'Hello')
        self.assertNotIn('secret', str(error.exception))
        post.assert_called_once()

    def test_jooble_requests_more_results_without_more_calls(self):
        company = {'id': 1, 'enabled': 1}
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({'jobs': []}).encode()
        for count in (20, 50, 100):
            filters = validate_filters({'keywords': 'product engineer', 'sources': ['jooble'], 'country': 'BR', 'jooble_count': count}, [company])
            with patch.dict('os.environ', {'JOOBLE_API_KEY_BR': 'fake', 'WEB_MAX_MARKET_QUERIES': '1'}, clear=True), patch.object(requests, 'post', return_value=response) as post:
                providers.jooble(filters)
            post.assert_called_once()
            self.assertEqual(post.call_args.kwargs['json']['ResultOnPage'], count)
        for invalid in (0, 101, -1, True, '100'):
            with self.assertRaises(ValueError):
                validate_filters({'keywords': 'product engineer', 'jooble_count': invalid}, [company])

    def test_100_jobs_are_batched_and_deduplicated_but_101_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / 'db.sqlite')
            client = app.test_client()
            csrf = client.get('/api/auth/session').json['csrf']
            account = client.post('/api/auth/register', headers={'X-Hunter-CSRF': csrf}, json={'email': 'test@example.org', 'name': 'Test', 'password': 'test-password-long'})
            owner = account.json['user']['id']
            headers = {'X-Hunter-CSRF': account.json['csrf']}
            store = app.extensions['store']
            jobs = [providers.make_job('Product Engineer', 'Factory', 'Curitiba, Brazil', f'https://example.org/job/{i}', 'Factory', country='BR', salary='BRL 8000 per month') for i in range(100)]
            filters = validate_filters({'keywords': 'product engineer'}, store.companies(owner))
            store.start_search('many-jobs', filters, owner)
            store.finish_search('many-jobs', {'jobs': jobs}, user_id=owner)
            body = {'ids': [job['id'] for job in jobs], 'channels': ['telegram'], 'search_id': 'many-jobs'}
            with patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'fake', 'TELEGRAM_CHAT_ID': '123'}), patch.object(main, 'send_telegram') as send, patch('web.TelegramPacer.send', side_effect=lambda sender, token, chat, message: sender(token, chat, message)):
                response = client.post('/api/notify', json=body, headers=headers)
                again = client.post('/api/notify', json=body, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['reports'][0]['sent'], 100)
            self.assertEqual(again.json['reports'][0]['sent'], 0)
            self.assertGreater(send.call_count, 1)
            self.assertTrue(all(len(call.args[2]) <= 4096 for call in send.call_args_list))
            self.assertTrue(all(store.delivered(job['id'], 'telegram', owner) for job in jobs))
            self.assertEqual(client.post('/api/notify', headers=headers, json={**body, 'ids': body['ids'] + ['extra']}).status_code, 400)
            app.extensions['executor'].shutdown(wait=True)


if __name__ == '__main__':
    unittest.main()
