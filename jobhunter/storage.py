"""Persistência SQLite/PostgreSQL com migração e isolamento por proprietário."""
import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from werkzeug.security import check_password_hash, generate_password_hash
from .company_catalog import DEFAULT_COMPANIES
from .database import connection, insert_id

DEFAULT_COMPANY = DEFAULT_COMPANIES[0]

class Store:
    def __init__(self, path, database_url='', recover_searches=True):
        self.path = Path(path)
        self.database_url = database_url
        self.is_postgres = bool(database_url)
        if not self.is_postgres:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            if self.is_postgres:
                db.execute('BEGIN IMMEDIATE')
            legacy = None if self.is_postgres else db.execute("SELECT 1 FROM sqlite_master WHERE name='companies'").fetchone()
            if legacy and 'user_id' not in {row['name'] for row in db.execute('PRAGMA table_info(companies)')}:
                backup = sqlite3.connect(str(self.path) + '.before-users.bak')
                try:
                    db.backup(backup)
                finally:
                    backup.close()
                db.execute('BEGIN IMMEDIATE')
                for table in ('companies', 'searches', 'favorites', 'deliveries'):
                    db.execute(f'ALTER TABLE {table} RENAME TO legacy_{table}')
            schema = [
                "CREATE TABLE IF NOT EXISTS companies (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL, url TEXT NOT NULL, provider TEXT NOT NULL, identifier TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, UNIQUE(user_id,url))",
                "CREATE TABLE IF NOT EXISTS searches (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL DEFAULT 0, filters TEXT NOT NULL, status TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS favorites (user_id INTEGER NOT NULL DEFAULT 0, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(user_id,id))",
                "CREATE TABLE IF NOT EXISTS deliveries (user_id INTEGER NOT NULL DEFAULT 0, job_id TEXT NOT NULL, channel TEXT NOT NULL, PRIMARY KEY(user_id,job_id,channel))",
                "CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS job_index (user_id INTEGER NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, signature TEXT NOT NULL, PRIMARY KEY(user_id,id))",
                "CREATE TABLE IF NOT EXISTS job_aliases (user_id INTEGER NOT NULL, source_id TEXT NOT NULL, job_id TEXT NOT NULL, PRIMARY KEY(user_id,source_id))",
                "CREATE TABLE IF NOT EXISTS email_outbox (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, recipient TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, available DOUBLE PRECISION NOT NULL, lease DOUBLE PRECISION NOT NULL DEFAULT 0)",
                "CREATE TABLE IF NOT EXISTS email_pending (user_id INTEGER NOT NULL, job_id TEXT NOT NULL, outbox_id TEXT NOT NULL, PRIMARY KEY(user_id,job_id))",
                "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, preferences TEXT NOT NULL DEFAULT '{}', contacts TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS sessions (digest TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires REAL NOT NULL)",
                "CREATE TABLE IF NOT EXISTS rate_limits (bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL)",
                "CREATE INDEX IF NOT EXISTS search_owner ON searches(user_id,created_at)",
            ]
            for statement in schema:
                if self.is_postgres:
                    statement = statement.replace('id INTEGER PRIMARY KEY', 'id BIGSERIAL PRIMARY KEY').replace('expires REAL', 'expires DOUBLE PRECISION')
                db.execute(statement)
            if not self.is_postgres and db.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_companies'").fetchone():
                db.execute('INSERT INTO companies SELECT id,0,name,url,provider,identifier,enabled FROM legacy_companies')
                db.execute('INSERT INTO searches SELECT id,0,filters,status,result,created_at FROM legacy_searches')
                db.execute('INSERT INTO favorites SELECT 0,id,payload FROM legacy_favorites')
                db.execute('INSERT INTO deliveries SELECT 0,job_id,channel FROM legacy_deliveries')
                for table in ('companies', 'searches', 'favorites', 'deliveries'):
                    db.execute(f'DROP TABLE legacy_{table}')
            if recover_searches:
                db.execute("UPDATE searches SET status='interrupted' WHERE status='running'")
            if not db.execute('SELECT 1 FROM metadata WHERE name=?', ('job-identities-v1',)).fetchone():
                # Preservamos os IDs antigos em aliases para não reenviar alertas históricos.
                from .job_identity import remember
                for row in db.execute('SELECT user_id,payload FROM favorites').fetchall():
                    remember(db, json.loads(row['payload']), row['user_id'])
                for row in db.execute('SELECT user_id,result FROM searches').fetchall():
                    result = json.loads(row['result'])
                    for job in result.get('jobs', []) + result.get('review_jobs', []):
                        remember(db, job, row['user_id'])
                db.execute('INSERT INTO metadata VALUES(?,?)', ('job-identities-v1', 'true'))
            owners = [row['id'] for row in db.execute('SELECT id FROM users')] or [0]
            for owner in owners:
                flag = f'company-catalog-v2:{owner}'
                if not db.execute('SELECT 1 FROM metadata WHERE name=?', (flag,)).fetchone():
                    self.seed_companies(owner, db)
                    db.execute('INSERT INTO metadata VALUES(?,?)', (flag, 'true'))

    @contextmanager
    def connection(self):
        with connection(self.path, self.database_url) as db:
            yield db

    def settings(self):
        with self.connection() as db:
            return {row['name']: row['value'] for row in db.execute('SELECT name,value FROM settings')}

    def setting(self, name, default=None):
        with self.connection() as db:
            row = db.execute('SELECT value FROM settings WHERE name=?', (name,)).fetchone()
        return row['value'] if row else default

    def set_setting(self, name, value, only_if_missing=False):
        with self.connection() as db:
            suffix = 'DO NOTHING' if only_if_missing else 'DO UPDATE SET value=excluded.value'
            db.execute('INSERT INTO settings(name,value) VALUES(?,?) ON CONFLICT(name) ' + suffix, (name, value))

    def seed_companies(self, user_id, db):
        for company in DEFAULT_COMPANIES:
            db.execute('INSERT INTO companies(user_id,name,url,provider,identifier) VALUES(?,?,?,?,?) ON CONFLICT(user_id,url) DO NOTHING',
                       (user_id, *(company[key] for key in ('name', 'url', 'provider', 'identifier'))))

    def companies(self, user_id=0):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM companies WHERE user_id=? ORDER BY name', (user_id,))]

    def add_company(self, company, user_id=0):
        with self.connection() as db:
            return insert_id(db, 'INSERT INTO companies(user_id,name,url,provider,identifier) VALUES(?,?,?,?,?)',
                             (user_id, *(company[key] for key in ('name', 'url', 'provider', 'identifier'))))

    def update_company(self, identifier, enabled=None, remove=False, user_id=0):
        with self.connection() as db:
            cursor = (db.execute('DELETE FROM companies WHERE id=? AND user_id=?', (identifier, user_id)) if remove else
                      db.execute('UPDATE companies SET enabled=? WHERE id=? AND user_id=?', (int(bool(enabled)), identifier, user_id)))
            return bool(cursor.rowcount)

    def start_search(self, identifier, filters, user_id=0):
        with self.connection() as db:
            db.execute('INSERT INTO searches(id,user_id,filters,status,created_at) VALUES(?,?,?,?,?)',
                       (identifier, user_id, json.dumps(filters), 'running', datetime.now(timezone.utc).isoformat()))

    def expire_searches(self, user_id, seconds=360):
        # Uma nova instância não interrompe buscas ativas de outra instância.
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
        with self.connection() as db:
            db.execute("UPDATE searches SET status='interrupted' WHERE user_id=? AND status='running' AND created_at<?",
                       (user_id, cutoff))

    def finish_search(self, identifier, result, status='done', user_id=0):
        with self.connection() as db:
            from .job_identity import remember
            result = dict(result)
            for group in ('jobs', 'review_jobs'):
                if group in result:
                    result[group] = list({job['canonical_id']: job for job in (remember(db, job, user_id) for job in result[group])}.values())
            db.execute('UPDATE searches SET result=?,status=? WHERE id=? AND user_id=?', (json.dumps(result), status, identifier, user_id))

    def search(self, identifier, user_id=0):
        with self.connection() as db:
            row = db.execute('SELECT * FROM searches WHERE id=? AND user_id=?', (identifier, user_id)).fetchone()
        if row is None:
            return None
        return {'id': row['id'], 'status': row['status'], 'filters': json.loads(row['filters']),
                'created_at': row['created_at'], **json.loads(row['result'])}

    def recent_searches(self, user_id=0):
        with self.connection() as db:
            kind = "result::jsonb ->> 'kind'" if self.is_postgres else "json_extract(result,'$.kind')"
            # O banco devolve somente contagens e três prévias, sem carregar históricos inteiros.
            fields = []
            for group in ('jobs', 'review_jobs'):
                count = f"jsonb_array_length(COALESCE(result::jsonb -> '{group}','[]'::jsonb))" if self.is_postgres else f"COALESCE(json_array_length(result,'$.{group}'),0)"
                fields.append(f'{count} AS {group}_count')
                for index in range(3):
                    item = f"(result::jsonb -> '{group}' -> {index})::text" if self.is_postgres else f"json_extract(result,'$.{group}[{index}]')"
                    fields.append(f'{item} AS {group}_{index}')
            rows = db.execute(f"SELECT id,filters,status,created_at,{','.join(fields)} FROM searches WHERE user_id=? AND {kind} IS NULL ORDER BY created_at DESC LIMIT 20", (user_id,)).fetchall()
        result = []
        for row in rows:
            previews = [json.loads(row[f'{group}_{index}']) for group in ('jobs', 'review_jobs') for index in range(3) if row[f'{group}_{index}']][:3]
            result.append({'id': row['id'], 'status': row['status'], 'created_at': row['created_at'], 'filters': json.loads(row['filters']),
                           'jobs_count': row['jobs_count'], 'review_count': row['review_jobs_count'],
                           'preview_jobs': [{key: job.get(key, '') for key in ('id', 'title', 'company', 'location', 'link', 'salary_check')} for job in previews]})
        return result

    def found_jobs(self, user_id, status='all', limit=40, offset=0):
        # Consulta o índice privado já deduplicado, incluindo buscas anteriores às vinte recentes.
        field = "payload::jsonb -> 'salary_check' ->> 'status'" if self.is_postgres else "json_extract(payload,'$.salary_check.status')"
        verdict = f"COALESCE({field},'review')"
        allowed = ('eligible', 'review') if status == 'all' else (status,)
        placeholders = ','.join('?' for _ in allowed)
        condition = f"user_id=? AND {verdict} IN ({placeholders})"
        params = (user_id, *allowed)
        with self.connection() as db:
            counts = db.execute(f'SELECT {verdict} AS verdict,COUNT(*) AS n FROM job_index WHERE {condition} GROUP BY {verdict}', params).fetchall()
            rows = db.execute(f'SELECT payload FROM job_index WHERE {condition} ORDER BY id LIMIT ? OFFSET ?', (*params, limit, offset)).fetchall()
        return {'jobs': [json.loads(row['payload']) for row in rows], 'total': sum(row['n'] for row in counts),
                'eligible': sum(row['n'] for row in counts if row['verdict'] == 'eligible'),
                'review': sum(row['n'] for row in counts if row['verdict'] == 'review'), 'limit': limit, 'offset': offset}

    def indexed_job(self, identifier, user_id):
        from .job_identity import resolve
        with self.connection() as db:
            canonical = resolve(db, identifier, user_id)
            row = db.execute('SELECT payload FROM job_index WHERE user_id=? AND id=?', (user_id, canonical)).fetchone()
        return json.loads(row['payload']) if row else None

    def favorite(self, job, remove=False, user_id=0):
        with self.connection() as db:
            if remove:
                db.execute('DELETE FROM favorites WHERE id=? AND user_id=?', (job['id'], user_id))
            else:
                db.execute('INSERT INTO favorites VALUES(?,?,?) ON CONFLICT(user_id,id) DO UPDATE SET payload=excluded.payload', (user_id, job['id'], json.dumps(job)))

    def favorites(self, user_id=0):
        with self.connection() as db:
            return [json.loads(row['payload']) for row in db.execute('SELECT payload FROM favorites WHERE user_id=?', (user_id,))]

    def delivered(self, job_id, channel, user_id=0):
        with self.connection() as db:
            from .job_identity import resolve
            canonical = resolve(db, job_id, user_id)
            return bool(db.execute('SELECT 1 FROM deliveries d LEFT JOIN job_aliases a ON a.user_id=d.user_id AND a.source_id=d.job_id '
                                   'WHERE d.user_id=? AND d.channel=? AND COALESCE(a.job_id,d.job_id)=?', (user_id, channel, canonical)).fetchone())

    def mark_delivered(self, ids, channel, user_id=0):
        with self.connection() as db:
            from .job_identity import resolve
            db.executemany('INSERT INTO deliveries VALUES(?,?,?) ON CONFLICT(user_id,job_id,channel) DO NOTHING', [(user_id, resolve(db, identifier, user_id), channel) for identifier in ids])

    def has_users(self):
        with self.connection() as db:
            return bool(db.execute('SELECT 1 FROM users LIMIT 1').fetchone())

    def register(self, name, email, password):
        password_hash = generate_password_hash(password, method='scrypt')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            first = not db.execute('SELECT 1 FROM users LIMIT 1').fetchone()
            identifier = insert_id(db, 'INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                                   (name, email, password_hash, 'admin' if first else 'member', datetime.now(timezone.utc).isoformat()))
            if first:
                for table in ('companies', 'searches', 'favorites', 'deliveries', 'job_index', 'job_aliases', 'email_outbox', 'email_pending'):
                    db.execute(f'UPDATE {table} SET user_id=? WHERE user_id=0', (identifier,))
            else:
                self.seed_companies(identifier, db)
            db.execute('INSERT INTO metadata VALUES(?,?)', (f'company-catalog-v2:{identifier}', 'true'))
        return self.user(identifier)

    def user(self, identifier):
        with self.connection() as db:
            row = db.execute('SELECT id,email,name,role,preferences,contacts FROM users WHERE id=?', (identifier,)).fetchone()
        if not row:
            return None
        return {**dict(row), 'preferences': json.loads(row['preferences']), 'contacts': json.loads(row['contacts'])}

    def authenticate(self, email, password, dummy_hash):
        with self.connection() as db:
            row = db.execute('SELECT id,password_hash FROM users WHERE email=?', (email,)).fetchone()
        valid = check_password_hash(row['password_hash'] if row else dummy_hash, password)
        return self.user(row['id']) if row and valid else None

    def update_user(self, identifier, *, name=None, preferences=None, contacts=None, merge_contacts=False):
        with self.connection() as db:
            if merge_contacts and contacts is not None:
                # Alterar um destino preserva o outro, inclusive em requisições simultâneas.
                db.execute('BEGIN IMMEDIATE')
                current = db.execute('SELECT contacts FROM users WHERE id=?', (identifier,)).fetchone()
                contacts = {**json.loads(current['contacts']), **contacts}
            for field, value in [('name', name), ('preferences', preferences), ('contacts', contacts)]:
                if value is not None:
                    db.execute(f'UPDATE users SET {field}=? WHERE id=?', (value if field == 'name' else json.dumps(value), identifier))

    def new_session(self, user_id):
        token = secrets.token_urlsafe(48)
        with self.connection() as db:
            db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user_id, time.time() + 7 * 86400))
        return token

    def session_user(self, token):
        if not token:
            return None
        with self.connection() as db:
            row = db.execute('SELECT user_id FROM sessions WHERE digest=? AND expires>?', (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return self.user(row['user_id']) if row else None

    def revoke_session(self, token):
        with self.connection() as db:
            db.execute('DELETE FROM sessions WHERE digest=?', (hashlib.sha256(token.encode()).hexdigest(),))

    def change_password(self, user_id, password):
        password_hash = generate_password_hash(password, method='scrypt')
        with self.connection() as db:
            db.execute('UPDATE users SET password_hash=? WHERE id=?', (password_hash, user_id))
            db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))

    def rate_limit(self, bucket, limit, seconds):
        now = time.time()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM rate_limits WHERE expires<=?', (now,))
            db.execute('INSERT INTO rate_limits VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=rate_limits.count+1', (bucket, now + seconds))
            return db.execute('SELECT count FROM rate_limits WHERE bucket=?', (bucket,)).fetchone()['count'] <= limit
