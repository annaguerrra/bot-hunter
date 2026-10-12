"""Configurações privadas compartilhadas pela interface e pela automação."""
import os
import re
import json
from dotenv import set_key

PATTERN = re.compile(r'^(JOOBLE_API_KEY(?:_[A-Z]{2})?|GEMINI_API_KEY|SERPAPI_API_KEY|GEMINI_MODEL|GEMINI_SEARCH_MODEL|TELEGRAM_BOT_TOKEN|EMAIL_FROM|EMAIL_APP_PASSWORD|EMAIL_PROVIDER|SMTP_HOST|SMTP_PORT|JOOBLE_COUNTRY)$')


def load_settings(store):
    # O Actions recebe todas as chaves regionais em uma única Secret privada.
    regional = os.getenv('JOOBLE_KEYS_JSON', '')
    if regional:
        try:
            keys = json.loads(regional)
        except (ValueError, TypeError):
            raise ValueError('JOOBLE_KEYS_JSON deve ser um objeto JSON com países ISO e chaves.') from None
        if not isinstance(keys, dict) or any(not isinstance(code, str) or not re.fullmatch('[A-Z]{2}', code) or not isinstance(key, str) or not key for code, key in keys.items()):
            raise ValueError('JOOBLE_KEYS_JSON contém um país ou uma chave inválida.')
        for code, key in keys.items():
            os.environ['JOOBLE_API_KEY_' + code] = key
    saved = store.settings()
    for name, value in list(os.environ.items()):
        if PATTERN.fullmatch(name) and value and (not store.is_postgres or name not in saved or os.getenv('HUNTER_CONFIG_ENV_PRIORITY') == 'true'):
            store.set_setting(name, value)
            saved[name] = value
    if store.is_postgres:
        for name, value in saved.items():
            if PATTERN.fullmatch(name):
                os.environ[name] = value


def save_settings(store, env_path, changes):
    for name, value in changes.items():
        if not PATTERN.fullmatch(name):
            raise ValueError('Configuração não permitida.')
        store.set_setting(name, value)
        if not store.is_postgres:
            set_key(str(env_path), name, value, quote_mode='never')
        os.environ[name] = value
