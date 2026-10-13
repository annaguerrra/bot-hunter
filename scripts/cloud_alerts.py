"""Busca agendada nas duas fontes e envio da fila Gmail, com estado no Neon."""
import argparse
import os
import sys
import uuid
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from jobhunter.auth import contacts_for
from jobhunter.delivery import TelegramPacer
from jobhunter.configuration import load_settings
from jobhunter.email_queue import EmailQueue
from jobhunter.storage import Store
from jobhunter.usage import UsageBudget
from jobhunter import providers
from web import validate_filters


def run(search=False):
    store = Store(main.BASE_DIR / 'data' / 'hunter.sqlite', main.required_env('DATABASE_URL'), recover_searches=False)
    load_settings(store)
    queue = EmailQueue(store)
    pacer = TelegramPacer()
    if search:
        with store.connection() as db:
            accounts = [row['id'] for row in db.execute('SELECT id FROM users ORDER BY id')]
        accounts.sort(key=lambda identifier: float(store.setting(f'automation-last:{identifier}', '0')))
        budget = UsageBudget(store.path, store.database_url)
        for identifier in accounts:
            user = store.user(identifier)
            contacts = contacts_for(user)
            if not contacts.get('email_to') and not contacts.get('telegram_chat_id'):
                continue
            companies = store.companies(identifier)
            # Contas sem preferências usam os filtros públicos definidos em Variables.
            form = user['preferences'] or {'keywords': os.getenv('JOB_KEYWORDS', 'product engineer;production engineer;engenheiro de produto'),
                                          'profile': os.getenv('JOB_PROFILE', 'both'), 'salary_min': float(os.getenv('MIN_SALARY_BRL', '7000')),
                                          'country': os.getenv('JOB_COUNTRY', 'BR'), 'city': os.getenv('JOB_LOCATION', '')}
            # Preferências já validadas guardam termos como lista; o formulário recebe texto.
            form = dict(form)
            # O teto de Variables só se aplica a contas sem um padrão pessoal salvo.
            if not user['preferences']:
                form['salary_max'] = float(os.environ['MAX_SALARY_BRL']) if os.getenv('MAX_SALARY_BRL', '').strip() else None
            # Preferências explícitas prevalecem; novas contas usam a seleção econômica.
            form.setdefault('auto_sources', os.getenv('AUTO_SOURCE_ROUTING', 'true').lower() == 'true')
            for field in ('keywords', 'excluded'):
                if isinstance(form.get(field), list):
                    form[field] = ';'.join(form[field])
            sources = ['jooble'] if providers.jooble_keys() else []
            if os.getenv('SERPAPI_API_KEY'):
                sources.append('google')
            if os.getenv('GEMINI_ENABLED', 'false').lower() == 'true' and os.getenv('GEMINI_API_KEY'):
                sources.append('gemini')
            if companies and 'companies' in form.get('sources', ['companies']):
                sources.append('companies')
            if not sources:
                continue
            filters = validate_filters({**form, 'sources': sources, 'pages': 1}, companies)
            result = providers.run_search(filters, companies, usage=budget, user_id=identifier)
            search_id = uuid.uuid4().hex
            store.start_search(search_id, filters, identifier)
            store.finish_search(search_id, result, user_id=identifier)
            store.set_setting(f'automation-last:{identifier}', str(time.time()))
            jobs = store.search(search_id, identifier)['jobs'][:max(1, min(100, int(os.getenv('MAX_JOBS', '100'))))]
            contacts = contacts_for(user)
            if os.getenv('SEND_EMAIL', 'true') == 'true' and contacts.get('email_to'):
                selected = [job for job in jobs if not store.delivered(job['id'], 'email', identifier)]
                if selected:
                    queue.enqueue(identifier, contacts['email_to'], selected)
            if os.getenv('SEND_TELEGRAM', 'true') == 'true' and contacts.get('telegram_chat_id'):
                selected = [job for job in jobs if not store.delivered(job['id'], 'telegram', identifier)]
                try:
                    for ids, parts in main.telegram_batches([(job['id'], job) for job in selected]):
                        pacer.send(main.send_telegram, main.required_env('TELEGRAM_BOT_TOKEN'), contacts['telegram_chat_id'], '<b>Bot Hunter · oportunidades</b>\n\n' + '\n\n'.join(parts))
                        store.mark_delivered(ids, 'telegram', identifier)
                except Exception as exc:
                    print('Telegram indisponível (' + type(exc).__name__ + '); os envios confirmados foram preservados.')
    result = queue.process(lambda recipient, jobs: main.send_email(main.email_settings(recipient), jobs))
    print('Fila Gmail: ' + str(result['sent_jobs']) + ' vagas enviadas; ' + str(result['failed_batches']) + ' lotes com erro.')
    if result['failed_batches']:
        raise RuntimeError('Há e-mails com erro. Revise o serviço e tente novamente pelo perfil do destinatário.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--search', action='store_true')
    args = parser.parse_args()
    try:
        run(args.search)
    except Exception as exc:
        print('Automação falhou (' + type(exc).__name__ + '). Confira Secrets e Variables; nenhuma credencial foi exibida.', file=sys.stderr)
        sys.exit(1)
