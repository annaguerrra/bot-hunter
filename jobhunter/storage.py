"""Persistência SQLite com migração e isolamento por proprietário."""
import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from werkzeug.security import check_password_hash, generate_password_hash
from .company_catalog import DEFAULT_COMPANIES

DEFAULT_COMPANY = DEFAULT_COMPANIES[0]

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            legacy = db.execute("SELECT 1 FROM sqlite_master WHERE name='companies'").fetchone()
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
                "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, preferences TEXT NOT NULL DEFAULT '{}', contacts TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS sessions (digest TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires REAL NOT NULL)",
                "CREATE TABLE IF NOT EXISTS rate_limits (bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL)",
                "CREATE INDEX IF NOT EXISTS search_owner ON searches(user_id,created_at)",
            ]
            for statement in schema:
                db.execute(statement)
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_companies'").fetchone():
                db.execute('INSERT INTO companies SELECT id,0,name,url,provider,identifier,enabled FROM legacy_companies')
                db.execute('INSERT INTO searches SELECT id,0,filters,status,result,created_at FROM legacy_searches')
                db.execute('INSERT INTO favorites SELECT 0,id,payload FROM legacy_favorites')
                db.execute('INSERT INTO deliveries SELECT 0,job_id,channel FROM legacy_deliveries')
                for table in ('companies', 'searches', 'favorites', 'deliveries'):
                    db.execute(f'DROP TABLE legacy_{table}')
            db.execute("UPDATE searches SET status='interrupted' WHERE status='running'")
            owners = [row['id'] for row in db.execute('SELECT id FROM users')] or [0]
            for owner in owners:
                flag = f'company-catalog-v2:{owner}'
                if not db.execute('SELECT 1 FROM metadata WHERE name=?', (flag,)).fetchone():
                    self.seed_companies(owner, db)
                    db.execute('INSERT INTO metadata VALUES(?,?)', (flag, 'true'))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def seed_companies(self, user_id, db):
        for company in DEFAULT_COMPANIES:
            db.execute('INSERT OR IGNORE INTO companies(user_id,name,url,provider,identifier) VALUES(?,?,?,?,?)',
                       (user_id, *(company[key] for key in ('name', 'url', 'provider', 'identifier'))))

    def companies(self, user_id=0):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM companies WHERE user_id=? ORDER BY name', (user_id,))]

    def add_company(self, company, user_id=0):
        with self.connection() as db:
            return db.execute('INSERT INTO companies(user_id,name,url,provider,identifier) VALUES(?,?,?,?,?)',
                              (user_id, *(company[key] for key in ('name', 'url', 'provider', 'identifier')))).lastrowid

    def update_company(self, identifier, enabled=None, remove=False, user_id=0):
        with self.connection() as db:
            cursor = (db.execute('DELETE FROM companies WHERE id=? AND user_id=?', (identifier, user_id)) if remove else
                      db.execute('UPDATE companies SET enabled=? WHERE id=? AND user_id=?', (int(bool(enabled)), identifier, user_id)))
            return bool(cursor.rowcount)

    def start_search(self, identifier, filters, user_id=0):
        with self.connection() as db:
            db.execute('INSERT INTO searches(id,user_id,filters,status,created_at) VALUES(?,?,?,?,?)',
                       (identifier, user_id, json.dumps(filters), 'running', datetime.now(timezone.utc).isoformat()))

    def finish_search(self, identifier, result, status='done', user_id=0):
        with self.connection() as db:
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
            rows = db.execute("SELECT id,filters,status,created_at FROM searches WHERE user_id=? AND json_extract(result,'$.kind') IS NULL ORDER BY created_at DESC LIMIT 20", (user_id,)).fetchall()
        return [{**dict(row), 'filters': json.loads(row['filters'])} for row in rows]

    def favorite(self, job, remove=False, user_id=0):
        with self.connection() as db:
            if remove:
                db.execute('DELETE FROM favorites WHERE id=? AND user_id=?', (job['id'], user_id))
            else:
                db.execute('INSERT OR REPLACE INTO favorites VALUES(?,?,?)', (user_id, job['id'], json.dumps(job)))

    def favorites(self, user_id=0):
        with self.connection() as db:
            return [json.loads(row['payload']) for row in db.execute('SELECT payload FROM favorites WHERE user_id=?', (user_id,))]

    def delivered(self, job_id, channel, user_id=0):
        with self.connection() as db:
            return bool(db.execute('SELECT 1 FROM deliveries WHERE job_id=? AND channel=? AND user_id=?', (job_id, channel, user_id)).fetchone())

    def mark_delivered(self, ids, channel, user_id=0):
        with self.connection() as db:
            db.executemany('INSERT OR IGNORE INTO deliveries VALUES(?,?,?)', [(user_id, identifier, channel) for identifier in ids])

    def has_users(self):
        with self.connection() as db:
            return bool(db.execute('SELECT 1 FROM users LIMIT 1').fetchone())

    def register(self, name, email, password):
        password_hash = generate_password_hash(password, method='scrypt')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            first = not db.execute('SELECT 1 FROM users LIMIT 1').fetchone()
            identifier = db.execute('INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                                    (name, email, password_hash, 'admin' if first else 'member', datetime.now(timezone.utc).isoformat())).lastrowid
            if first:
                for table in ('companies', 'searches', 'favorites', 'deliveries'):
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

    def update_user(self, identifier, *, name=None, preferences=None, contacts=None):
        with self.connection() as db:
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
            db.execute('INSERT INTO rate_limits VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=count+1', (bucket, now + seconds))
            return db.execute('SELECT count FROM rate_limits WHERE bucket=?', (bucket,)).fetchone()['count'] <= limit
