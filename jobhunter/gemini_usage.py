"""Cotas Gemini compartilhadas, inclusive tentativas com erro, no mesmo banco."""
import os
from datetime import datetime, timedelta
from .database import connection
from .usage import BudgetExceeded

FREE_SEARCH_MODELS = {'gemini-2.5-flash', 'gemini-2.5-flash-lite'}


class GeminiBudget:
    def __init__(self, usage, user_id):
        self.usage, self.user_id = usage, user_id

    def policy(self, db):
        saved = {row['name']: row['value'] for row in db.execute("SELECT name,value FROM settings WHERE name LIKE 'gemini_%'")}
        return {
            'user_daily': max(1, min(100, int(saved.get('gemini_user_daily', os.getenv('GEMINI_USER_DAILY_LIMIT', '2'))))),
            'global_daily': max(1, min(100, int(saved.get('gemini_global_daily', os.getenv('GEMINI_GLOBAL_DAILY_LIMIT', '6'))))),
            'monthly': max(1, min(1000, int(saved.get('gemini_monthly', os.getenv('GEMINI_MONTHLY_LIMIT', '60'))))),
            'token_budget': max(8192, min(1000000, int(os.getenv('GEMINI_DAILY_TOKEN_BUDGET', '100000')))),
            'auto_enabled': saved.get('gemini_auto_enabled', os.getenv('GEMINI_AUTO_FALLBACK', 'false')) == 'true',
            'search_model': os.getenv('GEMINI_AUTO_SEARCH_MODEL', '').strip(),
        }

    def counters(self):
        day, reset = self.usage.date_info()
        return [(day, f'gemini:user:{self.user_id}', 'user_daily'),
                (day, 'gemini:daily', 'global_daily'), (day[:7], 'gemini:monthly', 'monthly')], reset

    def pause_name(self):
        return 'gemini_pause_' + self.usage.fingerprint(os.getenv('GEMINI_API_KEY', ''))

    def snapshot(self):
        counters, reset = self.counters()
        with connection(self.usage.path, self.usage.database_url) as db:
            policy = self.policy(db)
            counts = [db.execute('SELECT count FROM usage_daily WHERE day=? AND bucket=?', (period, bucket)).fetchone() for period, bucket, _ in counters]
            pause = db.execute('SELECT value FROM settings WHERE name=?', (self.pause_name(),)).fetchone()
            tokens = db.execute('SELECT count FROM usage_daily WHERE day=? AND bucket=?', (counters[0][0], 'gemini:tokens')).fetchone()
        used = [row['count'] if row else 0 for row in counts]
        remaining = [max(0, policy[key] - count) for (_, _, key), count in zip(counters, used)]
        blocked_until = float(pause['value']) if pause else 0
        token_remaining = max(0, policy['token_budget'] - (tokens['count'] if tokens else 0))
        next_month = (datetime.fromisoformat(reset).replace(day=28) + timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        return {**policy, 'used_today': used[0], 'global_used_today': used[1], 'used_month': used[2],
                'remaining_today': min(remaining), 'token_remaining': token_remaining,
                'blocked_until': blocked_until, 'blocked': not min(remaining) or token_remaining < 512 or blocked_until > self.usage.clock(),
                'resets_at': next_month if not remaining[2] else reset,
                'search_available': policy['search_model'] in FREE_SEARCH_MODELS,
                'note': 'Tentativas e reserva conservadora de tokens compartilhadas entre site e Actions; uso externo não está incluído.'}

    def reserve(self, token_estimate):
        counters, _ = self.counters()
        with connection(self.usage.path, self.usage.database_url) as db:
            db.execute('BEGIN IMMEDIATE')
            policy = self.policy(db)
            pause = db.execute('SELECT value FROM settings WHERE name=?', (self.pause_name(),)).fetchone()
            if pause and float(pause['value']) > self.usage.clock():
                raise BudgetExceeded('Gemini está em pausa após falha ou limite do provedor. As atividades sem IA continuam disponíveis.')
            for period, bucket, key in counters:
                row = db.execute('SELECT count FROM usage_daily WHERE day=? AND bucket=?', (period, bucket)).fetchone()
                if (row['count'] if row else 0) >= policy[key]:
                    raise BudgetExceeded('A cota pessoal, compartilhada ou mensal Gemini terminou. Continue com histórico, favoritos e sites de empresas.')
            period = counters[0][0]
            tokens = db.execute('SELECT count FROM usage_daily WHERE day=? AND bucket=?', (period, 'gemini:tokens')).fetchone()
            if (tokens['count'] if tokens else 0) + token_estimate > policy['token_budget']:
                raise BudgetExceeded('O orçamento conservador de tokens Gemini não comporta esta chamada. As alternativas sem IA foram preservadas.')
            for period, bucket, _ in counters:
                db.execute('INSERT INTO usage_daily VALUES(?,?,1) ON CONFLICT(day,bucket) DO UPDATE SET count=usage_daily.count+1', (period, bucket))
            db.execute('INSERT INTO usage_daily VALUES(?,?,?) ON CONFLICT(day,bucket) DO UPDATE SET count=usage_daily.count+excluded.count',
                       (counters[0][0], 'gemini:tokens', token_estimate))

    def pause(self, seconds=3600):
        with connection(self.usage.path, self.usage.database_url) as db:
            db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',
                       (self.pause_name(), str(self.usage.clock() + max(60, min(seconds, 86400)))))

    def configure(self, user_daily, global_daily, monthly, auto_enabled):
        if any(type(value) is not int or not 1 <= value <= maximum for value, maximum in [(user_daily, 100), (global_daily, 100), (monthly, 1000)]) or type(auto_enabled) is not bool:
            raise ValueError('Informe limites Gemini válidos e a permissão para assistência automática.')
        with connection(self.usage.path, self.usage.database_url) as db:
            db.execute('BEGIN IMMEDIATE')
            for name, value in [('gemini_user_daily', user_daily), ('gemini_global_daily', global_daily), ('gemini_monthly', monthly), ('gemini_auto_enabled', str(auto_enabled).lower())]:
                db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value', (name, str(value)))
