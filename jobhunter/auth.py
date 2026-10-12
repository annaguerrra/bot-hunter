"""Autenticação por sessão revogável e controles de acesso da interface."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import timedelta

from flask import g, jsonify, request, session
from werkzeug.security import generate_password_hash


def public_user(user):
    return {key: user[key] for key in ('id', 'name', 'email', 'role')}


def contacts_for(user):
    # Só a conta que herdou o projeto recebe os destinos locais anteriores.
    defaults = {'telegram_chat_id': os.getenv('TELEGRAM_CHAT_ID', ''), 'email_to': os.getenv('EMAIL_TO', '')} if user['role'] == 'admin' else {}
    return {**defaults, **user['contacts']}


def configure_auth(app, store):
    secret_path = store.path.parent / 'session-secret.key'
    if store.is_postgres:
        store.set_setting('SESSION_SIGNING_KEY', os.getenv('HUNTER_SESSION_SECRET') or secrets.token_hex(32), only_if_missing=True)
        secret = store.settings()['SESSION_SIGNING_KEY']
    elif not secret_path.exists():
        try:
            with secret_path.open('x', encoding='ascii') as file:
                file.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    if not store.is_postgres:
        secret = secret_path.read_text(encoding='ascii').strip()
    trusted_hosts = os.getenv('HUNTER_TRUSTED_HOSTS', '127.0.0.1,localhost,::1').split(',')
    app.config.update(SECRET_KEY=secret,
                      SESSION_COOKIE_NAME='hunter_session', SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('HUNTER_HTTPS', '').lower() == 'true',
                      PERMANENT_SESSION_LIFETIME=timedelta(days=7),
                      TRUSTED_HOSTS=trusted_hosts)
    dummy = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')

    @app.before_request
    def require_account():
        if request.path == '/health':
            return
        g.user = store.session_user(session.get('token'))
        session.setdefault('csrf', secrets.token_urlsafe(32))
        if request.path.startswith('/api/') and not request.path.startswith('/api/auth/'):
            if not g.user:
                return jsonify(error='Entre na sua conta para continuar.'), 401
            if request.path.startswith('/api/integrations/') and g.user['role'] != 'admin':
                return jsonify(error='Somente a administração pode alterar as chaves de pesquisa compartilhadas.'), 403
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            supplied = request.headers.get('X-Hunter-CSRF', '')
            if not hmac.compare_digest(supplied, session['csrf']):
                return jsonify(error='Atualize a página antes de continuar.'), 403

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError('Envie um formulário válido.')
        return value

    def credentials(value):
        email, password = value.get('email', ''), value.get('password', '')
        if not isinstance(email, str) or not isinstance(password, str) or not 1 <= len(password) <= 128:
            raise ValueError('Informe e-mail e senha válidos.')
        email = email.strip().casefold()
        if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise ValueError('Informe um e-mail válido.')
        return email, password

    def limit(action, email=''):
        # Persistido no banco; não depende de estado em memória de um worker.
        buckets = [(f'{action}:ip:{request.remote_addr}', 12)]
        if email:
            buckets.append((f'{action}:account:{email}', 8))
        for key, maximum in buckets:
            bucket = hmac.new(app.secret_key.encode(), key.encode(), hashlib.sha256).hexdigest()
            if not store.rate_limit(bucket, maximum, 900):
                return jsonify(error='Muitas tentativas. Aguarde 15 minutos antes de tentar novamente.'), 429

    def sign_in(user):
        if session.get('token'):
            store.revoke_session(session['token'])
        session.clear()
        session.update(token=store.new_session(user['id']), csrf=secrets.token_urlsafe(32))
        session.permanent = True
        return jsonify(user=public_user(user), csrf=session['csrf'])

    @app.get('/api/auth/session')
    def account():
        return jsonify(user=public_user(g.user) if g.user else None, csrf=session['csrf'],
                       first_account=not store.has_users(),
                       registration_open=not store.has_users() or os.getenv('HUNTER_ALLOW_REGISTRATION', 'true').lower() == 'true')

    @app.post('/api/auth/register')
    def register():
        value = body()
        email, password = credentials(value)
        limited = limit('register')
        if limited:
            return limited
        first = not store.has_users()
        if first and (os.getenv('HUNTER_SETUP_TOKEN') or request.remote_addr not in {'127.0.0.1', '::1'}):
            setup = os.getenv('HUNTER_SETUP_TOKEN', '')
            supplied = value.get('setup_token', '')
            if not setup or not isinstance(supplied, str) or not hmac.compare_digest(setup, supplied):
                return jsonify(error='Crie a primeira conta neste computador ou informe o código de instalação.'), 403
        if not first and os.getenv('HUNTER_ALLOW_REGISTRATION', 'true').lower() != 'true':
            return jsonify(error='O cadastro de novas contas está fechado.'), 403
        name = value.get('name', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or len(password) < 12:
            raise ValueError('Informe seu nome e uma senha de 12 a 128 caracteres.')
        try:
            user = store.register(name.strip(), email, password)
        except sqlite3.IntegrityError:
            return jsonify(error='Não foi possível criar a conta com esses dados. Tente entrar ou use outro e-mail.'), 409
        return sign_in(user), 201

    @app.post('/api/auth/login')
    def login():
        email, password = credentials(body())
        limited = limit('login', email)
        if limited:
            return limited
        user = store.authenticate(email, password, dummy)
        if not user:
            return jsonify(error='E-mail ou senha incorretos.'), 401
        return sign_in(user)

    @app.post('/api/auth/logout')
    def logout():
        store.revoke_session(session.get('token', ''))
        session.clear()
        return jsonify(ok=True)

    @app.post('/api/auth/password')
    def password():
        if not g.user:
            return jsonify(error='Entre na sua conta.'), 401
        value = body()
        new_password = value.get('new_password', '')
        old_password = value.get('password', '')
        limited = limit('password', g.user['email'])
        if limited:
            return limited
        if not isinstance(old_password, str) or not 1 <= len(old_password) <= 128 or not isinstance(new_password, str) or not 12 <= len(new_password) <= 128:
            raise ValueError('A nova senha deve ter de 12 a 128 caracteres.')
        if not store.authenticate(g.user['email'], old_password, dummy):
            return jsonify(error='Senha atual incorreta.'), 401
        store.change_password(g.user['id'], new_password)
        return sign_in(g.user)
