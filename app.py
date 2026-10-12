"""Entrada pública Flask no Vercel; persistência obrigatória no Neon."""
import os

# Não inicializamos SQLite temporário como substituto silencioso do banco real.
if not os.getenv('DATABASE_URL', '').startswith(('postgresql://', 'postgres://')):
    raise RuntimeError('Configure DATABASE_URL no ambiente privado do Vercel antes de publicar.')

os.environ.setdefault('HUNTER_SERVERLESS', 'true')
os.environ.setdefault('HUNTER_HTTPS', 'true')
os.environ.setdefault('EMAIL_DELIVERY_MODE', 'queue')
os.environ.setdefault('GEMINI_ENABLED', 'false')

from web import create_app

app = create_app()
