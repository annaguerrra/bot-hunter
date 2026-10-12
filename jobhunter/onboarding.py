"""Progresso privado do guia inicial e vínculo temporário com o Telegram."""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import requests
from flask import g, jsonify, request
from .auth import contacts_for

TOUR_STEPS = 10


def configure_onboarding(app, store):
    def progress():
        return json.loads(store.setting(f'onboarding:{g.user["id"]}', '{"tour_status":"new","tour_step":0}'))

    def configured(name):
        value = os.getenv(name, '').strip()
        return bool(value) and not value.startswith('COLE_')

    @app.get('/api/onboarding')
    def status():
        contacts = contacts_for(g.user)
        transport = configured('EMAIL_FROM') and configured('EMAIL_APP_PASSWORD')
        return jsonify(**progress(), contacts=contacts,
                       email_transport_ready=transport, telegram_transport_ready=configured('TELEGRAM_BOT_TOKEN'),
                       checklist={'email': bool(contacts.get('email_to')), 'telegram': bool(contacts.get('telegram_chat_id')),
                                  'preferences': bool(g.user['preferences'].get('keywords'))})

    @app.post('/api/onboarding')
    def save_progress():
        body = request.get_json(silent=True) or {}
        status, step = body.get('tour_status'), body.get('tour_step')
        if status not in {'paused', 'completed'} or type(step) is not int or not 0 <= step < TOUR_STEPS:
            raise ValueError('Informe uma etapa válida do guia inicial.')
        store.set_setting(f'onboarding:{g.user["id"]}', json.dumps({'tour_status': status, 'tour_step': step}))
        return jsonify(ok=True)

    def telegram(method, params=None):
        if not configured('TELEGRAM_BOT_TOKEN'):
            raise ValueError('O bot ainda precisa ser configurado pela administração. Você pode continuar usando as vagas no painel.')
        try:
            response = requests.get('https://api.telegram.org/bot' + os.environ['TELEGRAM_BOT_TOKEN'] + '/' + method,
                                    params=params or {}, timeout=10)
            if response.status_code == 409:
                raise ValueError('Outro serviço está recebendo mensagens deste bot. Peça à administração seu chat ID e cadastre-o manualmente.')
            response.raise_for_status()
            body = response.json()
            if not body.get('ok'):
                raise ValueError('O Telegram não aceitou a conexão. Peça à administração para conferir o bot.')
            return body['result']
        except (requests.RequestException, KeyError, TypeError):
            raise ValueError('Não foi possível conectar ao Telegram. Tente novamente mais tarde.') from None

    def limited(action, maximum):
        if not store.rate_limit(f'telegram-link:{action}:{g.user["id"]}', maximum, 60):
            raise ValueError('Aguarde um minuto antes de tentar vincular o Telegram novamente.')

    @app.post('/api/onboarding/telegram')
    def start_link():
        limited('start', 3)
        username = telegram('getMe').get('username', '')
        if not re.fullmatch(r'[A-Za-z0-9_]{5,32}', username):
            raise ValueError('O bot não possui um nome válido. Peça à administração para conferir sua configuração.')
        nonce = 'hunter_' + secrets.token_urlsafe(18)
        now = time.time()
        record = {'digest': hashlib.sha256(nonce.encode()).hexdigest(), 'created_at': now, 'expires': now + 600,
                  'bot': hashlib.sha256(os.environ['TELEGRAM_BOT_TOKEN'].encode()).hexdigest()}
        store.set_setting(f'telegram-link:{g.user["id"]}', json.dumps(record))
        return jsonify(url=f'https://t.me/{username}?start={nonce}', expires_in=600)

    @app.post('/api/onboarding/telegram/confirm')
    def confirm_link():
        limited('confirm', 10)
        name = f'telegram-link:{g.user["id"]}'
        saved = store.setting(name)
        record = json.loads(saved or '{}')
        if record.get('expires', 0) < time.time() or record.get('bot') != hashlib.sha256(os.getenv('TELEGRAM_BOT_TOKEN', '').encode()).hexdigest():
            raise ValueError('O link expirou ou o bot mudou. Clique em Vincular Telegram para gerar outro link.')
        for update in telegram('getUpdates', {'timeout': 0, 'limit': 100}):
            message = update.get('message', {})
            text, chat = message.get('text', ''), message.get('chat', {})
            if not isinstance(text, str) or not text.startswith('/start '):
                continue
            digest = hashlib.sha256(text[len('/start '):].strip().encode()).hexdigest()
            if (not hmac.compare_digest(digest, record['digest']) or chat.get('type') != 'private'
                    or message.get('from', {}).get('id') != chat.get('id') or message.get('from', {}).get('is_bot')
                    or message.get('date', 0) < record['created_at'] - 5):
                continue
            with store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                active = db.execute('SELECT value FROM settings WHERE name=?', (name,)).fetchone()
                if not active or active['value'] != saved or record['expires'] < time.time():
                    raise ValueError('Este link já foi usado ou substituído. Gere outro link se precisar alterar seu Telegram.')
                user = db.execute('SELECT contacts FROM users WHERE id=?', (g.user['id'],)).fetchone()
                contacts = {**json.loads(user['contacts']), 'telegram_chat_id': str(chat['id'])}
                db.execute('UPDATE users SET contacts=? WHERE id=?', (json.dumps(contacts), g.user['id']))
                db.execute('DELETE FROM settings WHERE name=?', (name,))
            return jsonify(ok=True, chat_id=str(chat['id']))
        return jsonify(ok=False, pending=True, message='Abra o link pessoal, toque em Iniciar no Telegram e depois clique em Já iniciei o bot. Se não aparecer, cadastre o chat ID manualmente.')
