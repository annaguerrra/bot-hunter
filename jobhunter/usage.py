"""Cotas atômicas Jooble, rotação de países e cache de respostas públicas."""
import hashlib
import json
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .database import connection


class BudgetExceeded(RuntimeError):
    pass


class UsageBudget:
    def __init__(self, path, database_url='', clock=time.time):
        self.path, self.database_url, self.clock = path, database_url, clock
        if not database_url:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with connection(path, database_url) as db:
            db.execute('CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS usage_keys (fingerprint TEXT PRIMARY KEY, country TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0, prior_used INTEGER NOT NULL DEFAULT 0, calibrated INTEGER NOT NULL DEFAULT 0, last_used DOUBLE PRECISION NOT NULL DEFAULT 0, blocked_until DOUBLE PRECISION NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS usage_daily (day TEXT NOT NULL, bucket TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(day,bucket))')
            db.execute('CREATE TABLE IF NOT EXISTS query_cache (signature TEXT PRIMARY KEY, payload TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL)')

    @staticmethod
    def fingerprint(key):
        return hashlib.sha256(key.encode()).hexdigest()

    def date_info(self):
        now = datetime.fromtimestamp(self.clock(), ZoneInfo(os.getenv('HUNTER_BUDGET_TIMEZONE', 'America/Sao_Paulo')))
        return now.date().isoformat(), (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    @staticmethod
    def limits(db, user_id):
        saved = {row['name']: row['value'] for row in db.execute("SELECT name,value FROM settings WHERE name LIKE 'usage_%'")}
        return {'default_user_daily': int(saved.get('usage_user_daily', '12')),
                'user_daily': int(saved.get(f'usage_user_{user_id}', saved.get('usage_user_daily', '12'))),
                'global_daily': int(saved.get('usage_global_daily', '36')),
                'key_daily': int(saved.get('usage_key_daily', '6')), 'key_lifetime': 500}

    def reserve(self, user_id, country, key):
        day, reset = self.date_info()
        fingerprint = self.fingerprint(key)
        with connection(self.path, self.database_url) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO usage_keys(fingerprint,country) VALUES(?,?) ON CONFLICT(fingerprint) DO NOTHING', (fingerprint, country))
            record = db.execute('SELECT * FROM usage_keys WHERE fingerprint=?', (fingerprint,)).fetchone()
            limits = self.limits(db, user_id)
            if record['used'] + record['prior_used'] >= 500:
                raise BudgetExceeded('A estimativa de 500 consultas desta chave acabou. Explore empresas e oportunidades salvas; confira o saldo na Jooble.')
            if record['blocked_until'] > self.clock():
                raise BudgetExceeded('A Jooble limitou esta chave. Aguarde a liberação indicada no painel e explore empresas e vagas salvas.')
            buckets = [(f'user:{user_id}', limits['user_daily'], 'Seu limite diário de consultas Jooble'),
                       ('global', limits['global_daily'], 'O limite diário compartilhado de consultas Jooble'),
                       ('key:' + fingerprint, limits['key_daily'], 'O limite diário desta chave Jooble')]
            for bucket, maximum, label in buckets:
                row = db.execute('SELECT count FROM usage_daily WHERE day=? AND bucket=?', (day, bucket)).fetchone()
                if (row['count'] if row else 0) >= maximum:
                    raise BudgetExceeded(label + ' foi atingido. Renova à meia-noite de São Paulo. Use o histórico, vagas salvas ou sites de empresas.')
            for bucket, _, _ in buckets:
                db.execute('INSERT INTO usage_daily VALUES(?,?,1) ON CONFLICT(day,bucket) DO UPDATE SET count=usage_daily.count+1', (day, bucket))
            db.execute('UPDATE usage_keys SET used=used+1,last_used=? WHERE fingerprint=?', (self.clock(), fingerprint))

    def block(self, key, exhausted=False, seconds=3600):
        with connection(self.path, self.database_url) as db:
            db.execute('INSERT INTO usage_keys(fingerprint,country) VALUES(?,?) ON CONFLICT(fingerprint) DO NOTHING', (self.fingerprint(key), ''))
            if exhausted:
                db.execute('UPDATE usage_keys SET prior_used=500-used,calibrated=1 WHERE fingerprint=?', (self.fingerprint(key),))
            else:
                db.execute('UPDATE usage_keys SET blocked_until=? WHERE fingerprint=?', (self.clock() + max(60, min(seconds, 86400)), self.fingerprint(key)))

    def snapshot(self, user_id, keys, admin=False):
        day, reset = self.date_info()
        with connection(self.path, self.database_url) as db:
            limits = self.limits(db, user_id)
            daily = {row['bucket']: row['count'] for row in db.execute('SELECT bucket,count FROM usage_daily WHERE day=?', (day,))}
            records = {row['fingerprint']: dict(row) for row in db.execute('SELECT * FROM usage_keys')}
        remaining_user = max(0, limits['user_daily'] - daily.get(f'user:{user_id}', 0))
        remaining_global = max(0, limits['global_daily'] - daily.get('global', 0))
        markets = []
        for code, key in keys.items():
            fp = self.fingerprint(key)
            record = records.get(fp, {'used': 0, 'prior_used': 0, 'calibrated': 0, 'last_used': 0, 'blocked_until': 0})
            remaining = max(0, 500 - record['used'] - record['prior_used'])
            available = min(remaining, max(0, limits['key_daily'] - daily.get('key:' + fp, 0)))
            if record['blocked_until'] > self.clock():
                available = 0
            markets.append({'country': code, 'remaining_estimate': remaining, 'today_remaining': available,
                            'used_tracked': record['used'], 'prior_used': record['prior_used'],
                            'calibrated': bool(record['calibrated']), 'last_used': record['last_used'],
                            'blocked_until': record['blocked_until']})
        available_total = sum({self.fingerprint(keys[item['country']]): item['today_remaining'] for item in markets}.values())
        result = {'day': day, 'resets_at': reset, 'timezone': 'America/Sao_Paulo', 'limits': limits,
                  'used_today': daily.get(f'user:{user_id}', 0), 'remaining_today': min(remaining_user, remaining_global, available_total),
                  'global_used_today': daily.get('global', 0), 'global_remaining_today': remaining_global,
                  'blocked': not min(remaining_user, remaining_global, available_total),
                  'note': 'Contamos tentativas de chamada, inclusive falhas. O saldo total é estimado: ajuste consultas anteriores no painel administrativo.'}
        if admin:
            result['markets'] = markets
        return result

    def rank_markets(self, user_id, codes, keys):
        data = self.snapshot(user_id, keys, admin=True)
        markets = {item['country']: item for item in data['markets']}
        return sorted(codes, key=lambda code: (not markets[code]['today_remaining'], markets[code]['last_used'], -markets[code]['remaining_estimate'], codes.index(code)))

    def set_limits(self, user_daily, global_daily, key_daily, user_id=None):
        for value in (user_daily, global_daily, key_daily):
            if type(value) is not int or not 1 <= value <= 500:
                raise ValueError('Use limites inteiros entre 1 e 500 consultas.')
        entries = {f'usage_user_{user_id}' if user_id is not None else 'usage_user_daily': user_daily,
                   'usage_global_daily': global_daily, 'usage_key_daily': key_daily}
        with connection(self.path, self.database_url) as db:
            db.execute('BEGIN IMMEDIATE')
            for name, value in entries.items():
                db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value', (name, str(value)))

    def calibrate(self, country, key, remaining):
        if type(remaining) is not int or not 0 <= remaining <= 500:
            raise ValueError('Informe o saldo entre 0 e 500 consultas confirmado na Jooble.')
        fingerprint = self.fingerprint(key)
        with connection(self.path, self.database_url) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO usage_keys(fingerprint,country) VALUES(?,?) ON CONFLICT(fingerprint) DO NOTHING', (fingerprint, country))
            used = db.execute('SELECT used FROM usage_keys WHERE fingerprint=?', (fingerprint,)).fetchone()['used']
            if remaining > 500 - used:
                raise ValueError('O saldo excede as consultas já contadas para esta chave. Uma nova chave tem um contador próprio.')
            db.execute('UPDATE usage_keys SET prior_used=?,calibrated=1 WHERE fingerprint=?', (500-used-remaining, fingerprint))

    def cached(self, key, query):
        signature = self.fingerprint(key + json.dumps(query, sort_keys=True, ensure_ascii=True))
        with connection(self.path, self.database_url) as db:
            row = db.execute('SELECT payload FROM query_cache WHERE signature=? AND expires>?', (signature, self.clock())).fetchone()
        return json.loads(row['payload']) if row else None

    def remember(self, key, query, jobs, ttl=86400):
        signature = self.fingerprint(key + json.dumps(query, sort_keys=True, ensure_ascii=True))
        with connection(self.path, self.database_url) as db:
            db.execute('DELETE FROM query_cache WHERE expires<=?', (self.clock(),))
            db.execute('INSERT INTO query_cache VALUES(?,?,?) ON CONFLICT(signature) DO UPDATE SET payload=excluded.payload,expires=excluded.expires',
                       (signature, json.dumps(jobs), self.clock() + ttl))
