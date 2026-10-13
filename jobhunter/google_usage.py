"""Cota SerpAPI compartilhada, persistente e renovada por mês civil."""
import os
from datetime import datetime, timedelta
from .database import connection
from .usage import BudgetExceeded


class GoogleBudget:
    def __init__(self, usage):
        self.usage = usage

    def snapshot(self):
        day, reset = self.usage.date_info()
        month = day[:7]
        with connection(self.usage.path, self.usage.database_url) as db:
            settings = {row['name']: row['value'] for row in db.execute("SELECT name,value FROM settings WHERE name LIKE 'serp_%'")}
            daily = db.execute('SELECT count FROM usage_daily WHERE day=? AND bucket=?', (day, 'google:daily')).fetchone()
            monthly = db.execute('SELECT count FROM usage_daily WHERE day=? AND bucket=?', (month, 'google:monthly')).fetchone()
            prior = db.execute('SELECT count FROM usage_daily WHERE day=? AND bucket=?', (month, 'google:prior')).fetchone()
        daily_limit = max(1, min(int(settings.get('serp_daily_limit', os.getenv('SERPAPI_DAILY_LIMIT', '3'))), 250))
        monthly_limit = max(1, min(int(settings.get('serp_monthly_limit', os.getenv('SERPAPI_MONTHLY_LIMIT', '250'))), 250))
        used_daily, used_monthly = daily['count'] if daily else 0, monthly['count'] if monthly else 0
        used_monthly += prior['count'] if prior else 0
        next_month = (datetime.fromisoformat(reset).replace(day=28) + timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        return {'month': month, 'daily_limit': daily_limit, 'monthly_limit': monthly_limit,
                'used_today': used_daily, 'used_month': used_monthly,
                'remaining_today': max(0, min(daily_limit - used_daily, monthly_limit - used_monthly)),
                'remaining_month': max(0, monthly_limit - used_monthly),
                'blocked_until': float(settings.get('serp_blocked_until', '0')),
                'resets_at': next_month if used_monthly >= monthly_limit else reset,
                'note': 'Cota compartilhada entre painel e automação. Consultas anteriores fora da aplicação precisam ser ajustadas pela administração.'}

    def reserve(self):
        # O bloqueio do banco serializa as reservas feitas pelo site e pelo Actions.
        day, _ = self.usage.date_info()
        with connection(self.usage.path, self.usage.database_url) as db:
            db.execute('BEGIN IMMEDIATE')
            saved = {row['name']: row['value'] for row in db.execute("SELECT name,value FROM settings WHERE name LIKE 'serp_%'")}
            if float(saved.get('serp_blocked_until', '0')) > self.usage.clock():
                raise BudgetExceeded('Google Empregos está em pausa após limitar requisições. Use vagas salvas e páginas de empresas.')
            daily_limit = max(1, min(int(saved.get('serp_daily_limit', os.getenv('SERPAPI_DAILY_LIMIT', '3'))), 250))
            monthly_limit = max(1, min(int(saved.get('serp_monthly_limit', os.getenv('SERPAPI_MONTHLY_LIMIT', '250'))), 250))
            prior = db.execute('SELECT count FROM usage_daily WHERE day=? AND bucket=?', (day[:7], 'google:prior')).fetchone()
            for period, bucket, maximum, previous in [(day, 'google:daily', daily_limit, 0), (day[:7], 'google:monthly', monthly_limit, prior['count'] if prior else 0)]:
                row = db.execute('SELECT count FROM usage_daily WHERE day=? AND bucket=?', (period, bucket)).fetchone()
                if (row['count'] if row else 0) + previous >= maximum:
                    raise BudgetExceeded('Limite diário ou mensal do Google Empregos atingido. Continue pelas vagas salvas, histórico ou sites de empresas.')
            for period, bucket in [(day, 'google:daily'), (day[:7], 'google:monthly')]:
                db.execute('INSERT INTO usage_daily VALUES(?,?,1) ON CONFLICT(day,bucket) DO UPDATE SET count=usage_daily.count+1', (period, bucket))

    def pause(self, seconds=3600):
        with connection(self.usage.path, self.usage.database_url) as db:
            db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',
                       ('serp_blocked_until', str(self.usage.clock() + max(60, min(seconds, 86400)))))

    def configure(self, daily, monthly, prior=None):
        if type(daily) is not int or type(monthly) is not int or not 1 <= daily <= 250 or not 1 <= monthly <= 250:
            raise ValueError('Informe limites SerpAPI entre 1 e 250. O padrão recomendado é 3 por dia e 250 por mês.')
        if prior is not None and (type(prior) is not int or not 0 <= prior <= 250):
            raise ValueError('Informe o consumo anterior deste mês entre 0 e 250.')
        month = self.usage.date_info()[0][:7]
        with connection(self.usage.path, self.usage.database_url) as db:
            db.execute('BEGIN IMMEDIATE')
            for name, value in [('serp_daily_limit', daily), ('serp_monthly_limit', monthly)]:
                db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value', (name, str(value)))
            if prior is not None:
                db.execute('INSERT INTO usage_daily VALUES(?,?,?) ON CONFLICT(day,bucket) DO UPDATE SET count=excluded.count', (month, 'google:prior', prior))
