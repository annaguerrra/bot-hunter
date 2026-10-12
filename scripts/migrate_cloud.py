"""Cópia privada única do SQLite local para um banco Neon vazio."""
import getpass
import json
import os
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from jobhunter.configuration import PATTERN
from jobhunter.storage import Store

BASE = Path(__file__).resolve().parents[1]
TABLES = ('users', 'companies', 'searches', 'favorites', 'deliveries', 'metadata', 'settings', 'usage_keys', 'usage_daily', 'query_cache', 'job_index', 'job_aliases', 'email_outbox', 'email_pending')


def migrate(source_path, database_url, env_values):
    if not database_url.startswith(('postgresql://', 'postgres://')):
        raise ValueError('Informe a conexão PostgreSQL copiada de Neon → Connect.')
    source = sqlite3.connect('file:' + Path(source_path).resolve().as_posix() + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    source.execute('BEGIN')
    try:
        from jobhunter.database import connection
        with connection(BASE / 'data' / 'cloud-bootstrap.sqlite', database_url) as db:
            exists = db.execute("SELECT to_regclass('users') AS existing").fetchone()['existing']
            if exists and db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                raise ValueError('O destino já possui contas. A importação só aceita um banco vazio e preserva o original.')
        target = Store(BASE / 'data' / 'cloud-bootstrap.sqlite', database_url=database_url)
        from jobhunter.usage import UsageBudget
        UsageBudget(target.path, database_url)
        counts = {}
        with target.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                raise ValueError('O destino já possui contas. A importação só aceita um banco vazio e preserva o original.')
            for table in ('companies', 'metadata'):
                db.execute(f'DELETE FROM {table}')
            available = {row['name'] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in TABLES:
                if table not in available:
                    continue
                rows = [dict(row) for row in source.execute(f'SELECT * FROM {table}')]
                for row in rows:
                    if table == 'searches' and row['status'] == 'running':
                        row['status'] = 'interrupted'
                    if table == 'users' and row['role'] == 'admin':
                        defaults = {'email_to': env_values.get('EMAIL_TO', ''), 'telegram_chat_id': env_values.get('TELEGRAM_CHAT_ID', '')}
                        row['contacts'] = json.dumps({**defaults, **json.loads(row['contacts'])})
                    columns = ','.join(row)
                    placeholders = ','.join('?' for _ in row)
                    db.execute(f'INSERT INTO {table}({columns}) VALUES({placeholders})', tuple(row.values()))
                counts[table] = len(rows)
            for name, value in env_values.items():
                if value and PATTERN.fullmatch(name):
                    db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value', (name, value))
            for table in ('users', 'companies'):
                db.execute(f"SELECT setval(pg_get_serial_sequence('{table}','id'), COALESCE((SELECT MAX(id) FROM {table}),1), (SELECT COUNT(*)>0 FROM {table}))")
        return counts
    finally:
        source.close()


if __name__ == '__main__':
    url = os.getenv('HUNTER_DEPLOY_DATABASE_URL') or getpass.getpass('Conexão Neon (oculta): ')
    try:
        result = migrate(BASE / 'data' / 'hunter.sqlite', url, dotenv_values(BASE / '.env'))
        print('Cópia concluída. Contagens de registros: ' + json.dumps(result))
        print('Configure DATABASE_URL nos GitHub Secrets e no .env privado da interface local. Contas e chaves foram preservadas.')
    except Exception as exc:
        if isinstance(exc, ValueError):
            print(str(exc))
        else:
            print('A cópia falhou (' + type(exc).__name__ + '). Confira a conexão e tente novamente; nenhuma chave foi exibida.')
        sys.exit(1)
