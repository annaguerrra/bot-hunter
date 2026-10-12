"""Cadastra Secrets criptografadas e Variables usando o login Git existente.

Executar localmente: python -m pip install PyNaCl; python scripts/setup_github.py
As credenciais vêm do .env privado e nunca são impressas nem versionadas.
"""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from dotenv import dotenv_values
from nacl.public import PublicKey, SealedBox
import requests

BASE = Path(__file__).resolve().parents[1]


def setup():
    origin = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], cwd=BASE, text=True).strip()
    if origin.removesuffix('.git') != 'https://github.com/annaguerrra/bot-hunter':
        raise ValueError('Confira o remoto antes de cadastrar credenciais neste projeto.')
    credential = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n', capture_output=True,
                                text=True, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'}, check=True)
    token = dict(line.split('=', 1) for line in credential.stdout.splitlines() if '=' in line).get('password')
    if not token:
        raise ValueError('Conecte sua conta GitHub no Git para cadastrar Secrets automaticamente.')
    session = requests.Session()
    session.headers.update({'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
    base = 'https://api.github.com/repos/annaguerrra/bot-hunter/actions'

    def call(method, path, payload=None):
        result = session.request(method, base + path, json=payload, timeout=25)
        if not result.ok:
            raise ValueError('GitHub retornou HTTP ' + str(result.status_code) + '. Confira permissões de Secrets/Variables.')
        return result.json() if result.content else {}

    # Somente os nomes das Secrets podem ser consultados; o GitHub não devolve valores.
    existing = {item['name'] for item in call('GET', '/secrets?per_page=100')['secrets']}
    values = dotenv_values(BASE / '.env')
    candidates = {name: values[name] for name in ('JOOBLE_API_KEY', 'SERPAPI_API_KEY', 'GEMINI_API_KEY', 'TELEGRAM_BOT_TOKEN', 'EMAIL_FROM', 'EMAIL_APP_PASSWORD') if values.get(name)}
    regional = {name.removeprefix('JOOBLE_API_KEY_'): value for name, value in values.items() if name.startswith('JOOBLE_API_KEY_') and value}
    if regional:
        candidates['JOOBLE_KEYS_JSON'] = json.dumps(regional)
    public = call('GET', '/secrets/public-key')
    box = SealedBox(PublicKey(base64.b64decode(public['key'])))
    created = []
    for name, value in candidates.items():
        # SerpAPI foi fornecida para esta configuração; outras Secrets já existentes são preservadas.
        if name in existing and name != 'SERPAPI_API_KEY':
            continue
        encrypted = base64.b64encode(box.encrypt(value.encode())).decode()
        call('PUT', '/secrets/' + name, {'encrypted_value': encrypted, 'key_id': public['key_id']})
        created.append(name)
    variables = {item['name'] for item in call('GET', '/variables?per_page=100')['variables']}
    defaults = {'GEMINI_ENABLED': 'false', 'SEND_EMAIL': 'true', 'SEND_TELEGRAM': 'true', 'SERPAPI_DAILY_LIMIT': '3',
                'SERPAPI_MONTHLY_LIMIT': '250', 'JOB_PROFILE': 'both', 'MIN_SALARY_BRL': '7000', 'MAX_JOBS': '100',
                'WEB_MAX_MARKET_QUERIES': '6', 'SMTP_HOST': 'smtp.gmail.com', 'SMTP_PORT': '465', 'HUNTER_ALLOW_REGISTRATION': 'true', 'CLOUD_ALERTS_ENABLED': 'true', 'JOB_COUNTRY': 'BR'}
    added = []
    for name, value in defaults.items():
        if name not in variables:
            call('POST', '/variables', {'name': name, 'value': value})
            added.append(name)
    missing_secrets = sorted({'DATABASE_URL', 'TELEGRAM_BOT_TOKEN', 'EMAIL_FROM', 'EMAIL_APP_PASSWORD', 'SERPAPI_API_KEY'} - existing - set(created))
    print(json.dumps({'secrets_cadastradas': created, 'variables_cadastradas': added,
                      'secrets_pendentes': missing_secrets, 'variables_pendentes': sorted({'CLOUD_ALERTS_ENABLED'} - variables - set(added))}, ensure_ascii=True))


if __name__ == '__main__':
    try:
        setup()
    except Exception as exc:
        print('Cadastro não concluído (' + type(exc).__name__ + '); confira permissões no GitHub. Nenhuma credencial foi exibida.', file=sys.stderr)
        sys.exit(1)
