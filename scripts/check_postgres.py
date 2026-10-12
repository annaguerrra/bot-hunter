"""Verificação PostgreSQL opcional em um schema isolado e descartável.

Defina HUNTER_TEST_DATABASE_URL com um banco de testes; a conexão não é exibida.
"""
import os
import sys
import tempfile
import uuid
from unittest.mock import patch
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from jobhunter.storage import Store
from jobhunter.usage import UsageBudget, BudgetExceeded
from scripts.migrate_cloud import migrate


def check(url):
    schema = 'hunter_qa_' + uuid.uuid4().hex
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    if 'options' in query:
        raise ValueError('Use uma conexão de testes sem options; o teste define um schema isolado.')
    query['options'] = '-csearch_path=' + schema
    isolated = urlunsplit(parts._replace(query=urlencode(query)))
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute('CREATE SCHEMA ' + schema)
        try:
            with psycopg.connect(isolated) as probe:
                if probe.execute('SELECT current_schema()').fetchone()[0] != schema:
                    raise ValueError('Use a conexão direta de testes: este endpoint não respeitou o schema isolado.')
            with tempfile.TemporaryDirectory() as directory:
                local = Store(Path(directory) / 'local.sqlite')
                owner = local.register('QA owner', 'owner@example.org', 'strong-test-password')['id']
                member = local.register('QA member', 'member@example.org', 'strong-test-password')['id']
                local.start_search('qa-search', {'keywords': ['product engineer']}, owner)
                local.finish_search('qa-search', {'jobs': []}, user_id=owner)
                local.favorite({'id': 'qa-job', 'title': 'Product Engineer'}, user_id=owner)
                local.mark_delivered(['qa-job'], 'email', owner)
                local.set_setting('GEMINI_API_KEY', 'qa-private-test-key')
                budget = UsageBudget(local.path)
                budget.set_limits(1, 5, 5)
                budget.reserve(owner, 'BR', 'qa-key')
                counts = migrate(local.path, isolated, {'JOOBLE_API_KEY_BR': 'qa-key', 'EMAIL_TO': 'owner@example.org'})
                cloud = Store(Path(directory) / 'cloud.sqlite', isolated)
                assert cloud.authenticate('owner@example.org', 'strong-test-password', '')
                assert cloud.search('qa-search', member) is None
                assert cloud.favorites(owner)[0]['id'] == 'qa-job' and not cloud.favorites(member)
                cloud.favorite({'id': 'qa-job', 'title': 'Updated'}, user_id=owner)
                assert cloud.favorites(owner)[0]['title'] == 'Updated'
                # IDs equivalentes de Jooble/Google permanecem unidos após reiniciar.
                from jobhunter import providers
                first = providers.make_job('Product Engineer','Example','Berlin','https://example.org/one','Jooble')
                second = providers.make_job('PRODUCT ENGINEER','Example','Berlin','https://example.org/two','Google Empregos')
                for identifier, job in [('qa-dedup-one',first),('qa-dedup-two',second)]:
                    cloud.start_search(identifier, {}, owner)
                    cloud.finish_search(identifier, {'jobs':[job]}, user_id=owner)
                cloud.mark_delivered([first['id']], 'telegram', owner)
                assert Store(cloud.path, isolated).delivered(second['id'],'telegram',owner)
                assert cloud.delivered('qa-job', 'email', owner) and not cloud.delivered('qa-job', 'email', member)
                cloud.mark_delivered(['qa-job'], 'email', owner)
                assert len(cloud.recent_searches(owner)) == 3
                assert cloud.settings()['GEMINI_API_KEY'] == 'qa-private-test-key'
                assert cloud.settings()['JOOBLE_API_KEY_BR'] == 'qa-key'
                assert cloud.user(owner)['contacts']['email_to'] == 'owner@example.org'
                cloud_budget = UsageBudget(cloud.path, isolated)
                assert cloud_budget.snapshot(owner, {'BR': 'qa-key'})['used_today'] == 1
                try:
                    cloud_budget.reserve(owner, 'BR', 'qa-key')
                    raise AssertionError('Daily limit was bypassed')
                except BudgetExceeded:
                    pass
                cloud_budget.remember('qa-key', {'keywords': 'qa'}, [])
                assert cloud_budget.cached('qa-key', {'keywords': 'qa'}) == []
                assert cloud.rate_limit('qa', 1, 60) and not cloud.rate_limit('qa', 1, 60)
                added = cloud.register('QA third', 'third@example.org', 'strong-test-password')['id']
                assert added > member
                try:
                    migrate(local.path, isolated, {})
                    raise AssertionError('Populated cloud database was overwritten')
                except ValueError:
                    pass
                assert cloud.search('qa-search', owner)
                # Simulamos duas funções sem disco gravável compartilhando sessões no Neon.
                from web import create_app
                with patch.dict(os.environ, {'DATABASE_URL': isolated, 'HUNTER_SERVERLESS': 'true',
                                             'GEMINI_ENABLED': 'false'}, clear=True), \
                        patch.object(Path, 'mkdir', side_effect=AssertionError('readonly function')):
                    first_app = create_app()
                    second_app = None
                    try:
                        first_store = first_app.extensions['store']
                        token = first_store.new_session(owner)
                        first_store.start_search('qa-active-serverless', {}, owner)
                        second_app = create_app()
                        assert first_app.secret_key == second_app.secret_key
                        second_store = second_app.extensions['store']
                        assert second_store.session_user(token)['id'] == owner
                        assert second_store.search('qa-active-serverless', owner)['status'] == 'running'
                    finally:
                        first_app.extensions['executor'].shutdown(wait=True)
                        if second_app:
                            second_app.extensions['executor'].shutdown(wait=True)
                print({'postgres_contract': 'passed', 'migration': 'passed', 'rows_copied': counts, 'isolation': 'passed', 'budgets': 'passed'})
        finally:
            admin.execute('DROP SCHEMA ' + schema + ' CASCADE')


if __name__ == '__main__':
    url = os.getenv('HUNTER_TEST_DATABASE_URL')
    if not url:
        raise SystemExit('Defina HUNTER_TEST_DATABASE_URL com uma conexão de testes para executar este contrato.')
    check(url)
