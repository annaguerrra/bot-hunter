"""Interface local: python web.py. O bot de linha de comando continua em main.py."""
import argparse
import os
import re
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, render_template, request, send_from_directory, session

import main
from jobhunter import geo, providers, salary, matching
from jobhunter.storage import Store
from jobhunter.jooble_markets import MARKETS, HOSTS
from jobhunter.auth import configure_auth, contacts_for, public_user
from jobhunter.delivery import TelegramPacer
from jobhunter.configuration import load_settings, save_settings
from jobhunter.usage import UsageBudget
from jobhunter import http

BASE = Path(__file__).resolve().parent
MAX_NOTIFY_JOBS = 100


def validate_filters(body, companies):
    if not isinstance(body, dict):
        raise ValueError("Envie um formulário de busca válido.")
    text = body.get("keywords", "")
    if not isinstance(text, str) or len(text) > 300:
        raise ValueError("Informe cargos com até 300 caracteres.")
    keywords = main.split_terms(text)
    if not 1 <= len(keywords) <= 3:
        raise ValueError("Informe de 1 a 3 cargos, separados por ponto e vírgula.")
    region = str(body.get("region", "")).upper()
    country = str(body.get("country", "")).upper()
    state = str(body.get("state", ""))
    if region and region not in geo.REGIONS:
        raise ValueError("Selecione uma região do mundo válida.")
    if country and country not in geo.BY_CODE:
        raise ValueError("Selecione um país válido.")
    if region and country and geo.BY_CODE[country]["region"] != region:
        raise ValueError("O país não pertence à região selecionada.")
    if state and (not country or state not in {item["code"] for item in geo.states(country)}):
        raise ValueError("Selecione um estado ou província do país escolhido.")
    free = body.get('free_exploration', False)
    if not isinstance(free, bool):
        raise ValueError('A opção de exploração em empresas deve ser true ou false.')
    sources = ['companies'] if free else body.get("sources", ["companies"])
    if sources == [] and body.get('auto_sources') is True:
        sources = ['jooble']
    if not isinstance(sources, list) or not sources or any(not isinstance(item, str) or item not in {"companies", "google", "jooble", "gemini"} for item in sources):
        raise ValueError("Selecione pelo menos uma fonte válida.")
    company_ids = body.get("company_ids", [company["id"] for company in companies if company["enabled"]])
    if not isinstance(company_ids, list) or any(type(item) is not int for item in company_ids):
        raise ValueError("Selecione empresas válidas.")
    valid_ids = {company["id"] for company in companies if company["enabled"]}
    if any(item not in valid_ids for item in company_ids):
        raise ValueError("Uma das empresas selecionadas está desativada ou não existe.")
    if "companies" in sources and not company_ids and (free or body.get('auto_sources') is not True):
        raise ValueError("Cadastre ou selecione uma empresa para consultar suas vagas.")
    try:
        pages = int(body.get("pages", 1))
    except (TypeError, ValueError):
        raise ValueError("O número de páginas deve ser um inteiro.") from None
    if pages not in {1, 2, 3}:
        raise ValueError("Escolha de 1 a 3 páginas por fonte e cargo.")
    city = body.get("city", "")
    excluded = body.get("excluded", "estágio;estagiário;aprendiz;intern;internship")
    if not isinstance(city, str) or len(city) > 100 or not isinstance(excluded, str) or len(excluded) > 300:
        raise ValueError("Cidade ou termos excluídos inválidos.")
    for key in ("strict_title", "remote", "multilingual", "auto_sources"):
        if key in body and not isinstance(body[key], bool):
            raise ValueError("As opções de cargo e remoto precisam ser true ou false.")
    profile = body.get("profile", "both")
    if not isinstance(profile, str) or profile not in {"product", "production", "both", "custom"}:
        raise ValueError("Escolha um perfil de engenharia válido.")
    minimum = body.get("salary_min", 7000)
    floor = 0 if profile == 'custom' else 7000
    if type(minimum) not in (int, float) or not floor <= minimum <= 1000000:
        raise ValueError(f'O salário mínimo deve ser de R$ {floor:,.0f} a R$ 1.000.000 por mês.')
    jooble_count = body.get('jooble_count', 100)
    if type(jooble_count) is not int or jooble_count not in {20, 50, 100}:
        raise ValueError('Escolha 20, 50 ou 100 resultados por consulta Jooble.')
    return {"keywords": keywords, "region": region, "country": country, "state": state,
            "city": city.strip(), "sources": list(dict.fromkeys(sources)), "company_ids": company_ids,
            "strict_title": body.get("strict_title", True), "remote": body.get("remote", False),
            "pages": pages, "excluded": main.split_terms(excluded), "profile": profile,
            "multilingual": body.get("multilingual", True), "salary_min": minimum, 'jooble_count': jooble_count,
            'auto_sources': False if free else body.get('auto_sources', False), 'free_exploration': free}


def create_app(db_path=None):
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=100_000, JSON_SORT_KEYS=False)
    serverless = os.getenv('HUNTER_SERVERLESS', '').lower() == 'true'
    app.json.ensure_ascii = False
    store = Store(db_path or BASE / "data" / "hunter.sqlite", database_url=os.getenv('DATABASE_URL', '') if db_path is None else '', recover_searches=not serverless)
    load_settings(store)
    usage = UsageBudget(store.path, store.database_url)
    app.extensions['usage'] = usage
    app.extensions["store"] = store
    configure_auth(app, store)
    from jobhunter.onboarding import configure_onboarding
    configure_onboarding(app, store)
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hunter")
    app.extensions["executor"] = executor
    search_slots = threading.BoundedSemaphore(2)
    delivery_lock = threading.Lock()
    telegram_pacer = TelegramPacer()
    configuration_lock = threading.Lock()

    @app.before_request
    def protect_mutations():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("Origin") and urlsplit(request.headers["Origin"]).netloc != request.host:
                return jsonify(error="Origem da requisição inválida."), 403
            if request.is_json and request.get_json(silent=True) is not None and not isinstance(request.get_json(silent=True), dict):
                raise ValueError('Envie um formulário JSON válido.')

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if not request.path.endswith("/grounding"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'"
        if request.path.startswith('/api') or request.path == '/':
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ValueError)
    def invalid_input(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(sqlite3.IntegrityError)
    def duplicate(_exc):
        return jsonify(error="Esta página de carreiras já está cadastrada."), 409

    @app.get("/")
    def index():
        return render_template('index.html' if g.user else 'login.html', csrf=session['csrf'],
                               first_account=not store.has_users(),
                               setup_required=bool(os.getenv('HUNTER_SETUP_TOKEN')),
                               registration_open=not store.has_users() or os.getenv('HUNTER_ALLOW_REGISTRATION', 'true').lower() == 'true')

    @app.get('/health')
    def health():
        with store.connection() as db:
            db.execute('SELECT 1')
        return jsonify(status='ok')

    @app.get("/assets/<path:filename>")
    def assets(filename):
        return send_from_directory(BASE / "assets", filename)

    @app.get("/api/config")
    def config():
        from jobhunter.gemini_usage import GeminiBudget
        auto_ai = os.getenv('AUTO_SOURCE_ROUTING', 'true').lower() == 'true' and GeminiBudget(usage, g.user['id']).snapshot()['auto_enabled']
        def configured(name):
            value = os.getenv(name, "").strip()
            return bool(value) and not value.startswith("COLE_")
        return jsonify(regions=[{"code": code, "name": name} for code, name in geo.REGIONS.items()],
                       countries=geo.COUNTRIES, companies=store.companies(g.user['id']), user=public_user(g.user),
                       preferences=g.user['preferences'],
                       limits={'max_notify_jobs': MAX_NOTIFY_JOBS, 'telegram_batch_jobs': 1 if serverless else MAX_NOTIFY_JOBS,
                               'company_search_limit': providers.company_search_limit(), 'company_registration_limit': 100},
                       jooble_countries=list(providers.jooble_keys()), jooble_markets=MARKETS,
                        integrations={"jooble": bool(providers.jooble_keys()), "google": configured("SERPAPI_API_KEY"), "gemini": configured("GEMINI_API_KEY") and (os.getenv('GEMINI_ENABLED', 'true').lower() == 'true' or auto_ai),
                                     "telegram": configured("TELEGRAM_BOT_TOKEN") and bool(contacts_for(g.user).get('telegram_chat_id')),
                                     "email": configured('EMAIL_FROM') and configured('EMAIL_APP_PASSWORD') and bool(contacts_for(g.user).get('email_to'))},
                       automatic_enabled=os.getenv('AUTO_SOURCE_ROUTING', 'true').lower() == 'true',
                       defaults={"keywords": "product engineer;production engineer;engenheiro de produto", "sources": ["companies"],
                                 "salary_min": 7000, "profile": "both"})

    @app.post("/api/integrations/gemini")
    def gemini_key():
        body = request.get_json(silent=True) or {}
        key = body.get("key", "")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{20,256}", key.strip()):
            raise ValueError("Informe uma chave Gemini válida do Google AI Studio.")
        with configuration_lock:
            save_settings(store, BASE / '.env', {'GEMINI_API_KEY': key.strip()})
        return jsonify(ok=True)

    @app.get('/api/integrations/email')
    def email_status():
        return jsonify(provider=os.getenv('EMAIL_PROVIDER', 'smtp'), sender=os.getenv('EMAIL_FROM', ''),
                       smtp_configured=bool(os.getenv('EMAIL_APP_PASSWORD')),
                       queued=os.getenv('EMAIL_DELIVERY_MODE') == 'queue')

    @app.post('/api/integrations/email')
    def email_configuration():
        body = request.get_json(silent=True) or {}
        provider, sender, password = body.get('provider'), body.get('sender', ''), body.get('password', '')
        if provider != 'smtp' or not isinstance(sender, str) or len(sender) > 254 or not re.fullmatch(r'[^\s@;]+@[^\s@;]+\.[^\s@;]+', sender):
            raise ValueError('Informe o serviço e um e-mail remetente válido.')
        if not isinstance(password, str) or len(password) > 300 or any(char in password for char in '\r\n'):
            raise ValueError('Informe uma credencial válida do serviço de e-mail.')
        credential = 'EMAIL_APP_PASSWORD'
        password = password.replace(' ', '')
        if not password and not os.getenv(credential):
            raise ValueError('Informe a chave API ou a senha de aplicativo do serviço escolhido.')
        if password and len(password) < 12:
            raise ValueError('A credencial do serviço de e-mail parece incompleta.')
        changes = {'EMAIL_PROVIDER': provider, 'EMAIL_FROM': sender}
        if password:
            changes[credential] = password
        with configuration_lock:
            save_settings(store, BASE / '.env', changes)
        return jsonify(ok=True)

    @app.get("/api/states/<country>")
    def states(country):
        if country not in geo.BY_CODE:
            raise ValueError("País inválido.")
        return jsonify(states=geo.states(country))

    @app.get('/api/profile')
    def profile():
        return jsonify(user=public_user(g.user), preferences=g.user['preferences'], contacts=contacts_for(g.user))

    @app.patch('/api/profile')
    def update_profile():
        body = request.get_json(silent=True) or {}
        name = body.get('name', g.user['name'])
        contacts = body.get('contacts', g.user['contacts'])
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or not isinstance(contacts, dict):
            raise ValueError('Informe nome e destinatários válidos.')
        email, chat = contacts.get('email_to', ''), contacts.get('telegram_chat_id', '')
        if not isinstance(email, str) or len(email) > 254 or (email and not re.fullmatch(r'[^\s@;]+@[^\s@;]+\.[^\s@;]+', email)):
            raise ValueError('Informe um único e-mail válido para seus alertas.')
        if not isinstance(chat, str) or (chat and not re.fullmatch(r'-?[0-9]{1,20}', chat)):
            raise ValueError('Informe o ID numérico do seu chat Telegram.')
        updates = {key: value.strip() for key, value in [('email_to', email), ('telegram_chat_id', chat)] if key in contacts}
        store.update_user(g.user['id'], name=name.strip(), contacts=updates, merge_contacts=True)
        return jsonify(ok=True)

    @app.post('/api/preferences')
    def save_preferences():
        filters = validate_filters(request.get_json(silent=True), store.companies(g.user['id']))
        store.update_user(g.user['id'], preferences=filters)
        return jsonify(ok=True, preferences=filters)

    @app.get('/api/usage')
    def usage_status():
        result = usage.snapshot(g.user['id'], providers.jooble_keys(), admin=g.user['role'] == 'admin')
        from jobhunter.google_usage import GoogleBudget
        result['google'] = GoogleBudget(usage).snapshot()
        from jobhunter.gemini_usage import GeminiBudget
        result['gemini'] = GeminiBudget(usage, g.user['id']).snapshot()
        if g.user['role'] == 'admin':
            with store.connection() as db:
                result['users'] = [dict(row) for row in db.execute('SELECT id,name FROM users ORDER BY name')]
                for user in result['users']:
                    user['daily_limit'] = usage.limits(db, user['id'])['user_daily']
        return jsonify(result)

    @app.post('/api/integrations/usage')
    def usage_settings():
        body = request.get_json(silent=True) or {}
        if body.get('action') == 'gemini':
            from jobhunter.gemini_usage import GeminiBudget
            GeminiBudget(usage, g.user['id']).configure(body.get('user_daily'), body.get('global_daily'), body.get('monthly'), body.get('auto_enabled'))
        elif body.get('action') == 'google':
            from jobhunter.google_usage import GoogleBudget
            GoogleBudget(usage).configure(body.get('daily'), body.get('monthly'), body.get('prior'))
        elif body.get('action') == 'balance':
            code = body.get('country')
            key = providers.jooble_keys().get(code)
            if not key:
                raise ValueError('Selecione um país com chave cadastrada.')
            usage.calibrate(code, key, body.get('remaining'))
        else:
            user_id = body.get('user_id')
            if user_id is not None and (type(user_id) is not int or not store.user(user_id)):
                raise ValueError('Selecione uma conta válida.')
            usage.set_limits(body.get('user_daily'), body.get('global_daily'), body.get('key_daily'), user_id)
        return jsonify(ok=True)

    @app.post('/api/guidance')
    def search_guidance():
        from jobhunter.guidance import guidance
        companies = store.companies(g.user['id'])
        body = request.get_json(silent=True)
        # Links e dicas independem de empresas cadastradas; validar não inicia busca.
        filters = validate_filters({**body, 'sources': ['jooble'], 'free_exploration': False} if isinstance(body, dict) else body, companies)
        return jsonify(**guidance(filters, companies), searches=store.recent_searches(g.user['id']),
                       favorites_count=len(store.favorites(g.user['id'])))

    @app.post('/api/companies/discover')
    def discover_companies():
        from jobhunter.discovery import suggest_companies
        body = request.get_json(silent=True) or {}
        filters = validate_filters(body, store.companies(g.user['id']))
        offset = body.get('discovery_offset', 0)
        use_gemini = body.get('use_gemini', False)
        if type(offset) is not int or not 0 <= offset <= 1000 or not isinstance(use_gemini, bool):
            raise ValueError('Opções de descoberta inválidas.')
        use_gemini = use_gemini and not filters['free_exploration']
        if not store.rate_limit(f'discovery:{g.user["id"]}', 5, 3600):
            return jsonify(error='Limite de cinco descobertas de empresas por hora atingido.'), 429
        if not search_slots.acquire(blocking=False):
            return jsonify(error='Há pesquisas em andamento. Aguarde antes de descobrir empresas.'), 429
        try:
            from jobhunter.gemini import usage_scope
            with http.deadline(240 if serverless else None), usage_scope(usage, g.user['id']):
                result = suggest_companies(filters, store.companies(g.user['id']), offset=offset, usage=usage, use_gemini=use_gemini)
            identifier = uuid.uuid4().hex
            store.start_search(identifier, filters, g.user['id'])
            store.finish_search(identifier, result, user_id=g.user['id'])
            return jsonify(id=identifier, **result)
        finally:
            search_slots.release()

    @app.post("/api/integrations/google")
    def google_key():
        body = request.get_json(silent=True) or {}
        key = body.get("key", "")
        if not isinstance(key, str) or not 20 <= len(key.strip()) <= 256 or not key.strip().isalnum():
            raise ValueError("Informe uma chave SerpAPI válida.")
        key = key.strip()
        with configuration_lock:
            save_settings(store, BASE / '.env', {'SERPAPI_API_KEY': key})
        return jsonify(ok=True)

    @app.post("/api/companies")
    def add_company():
        body = request.get_json(silent=True) or {}
        name, url = body.get("name", ""), body.get("url", "")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or not isinstance(url, str) or len(url) > 1000:
            raise ValueError("Informe o nome da empresa e sua página de carreiras.")
        try:
            company = providers.discover_company(name.strip(), url)
        except (providers.requests.RequestException, OSError):
            raise ValueError("Não foi possível acessar esse site. Confira a URL da página de carreiras.") from None
        result = store.add_companies([company], g.user['id'])
        return jsonify(id=result['ids'][0], existing=not bool(result['added']), **company), 201 if result['added'] else 200

    @app.get('/api/companies/catalog')
    def company_catalog():
        from jobhunter.company_catalog import catalog_page, AREAS, CATALOG_PROVIDERS
        try:
            offset = int(request.args.get('offset', '0'))
        except ValueError:
            raise ValueError('Página inválida.') from None
        q, provider, area = (request.args.get(key, '') for key in ('q', 'provider', 'area'))
        country, region, geography = (request.args.get(key, '') for key in ('country', 'region', 'geography'))
        profile = request.args.get('profile', 'both')
        if (not 0 <= offset <= 1000 or len(q) > 100 or provider and provider not in CATALOG_PROVIDERS | {'website'}
                or area and area not in AREAS or country and country not in geo.BY_CODE
                or region and region not in geo.REGIONS or geography not in {'', 'international'}
                or profile not in {'both', 'production', 'product', 'custom'}):
            raise ValueError('Filtros do catálogo inválidos.')
        return jsonify(**catalog_page(store.companies(g.user['id']), q=q, provider=provider, area=area,
                                     country=country, region=region, geography=geography, profile=profile, offset=offset))

    @app.post('/api/companies/catalog')
    def add_catalog_companies():
        from jobhunter.company_catalog import suggestions
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError('Selecione empresas do catálogo.')
        identifiers = body.get('ids')
        if not isinstance(identifiers, list) or not 1 <= len(identifiers) <= 20 or any(not isinstance(item, str) for item in identifiers):
            raise ValueError('Selecione de 1 a 20 empresas do catálogo.')
        known = {item['catalog_id']: item for item in suggestions()}
        if any(item not in known or known[item]['status'] != 'validated' or known[item]['provider'] not in providers.COMPANY_PROVIDERS for item in identifiers):
            raise ValueError('Somente integrações validadas podem entrar no radar pelo catálogo.')
        result = store.add_companies([known[item] for item in dict.fromkeys(identifiers)], g.user['id'])
        return jsonify(**result)

    @app.get('/api/career')
    def career_resources():
        from jobhunter.career_resources import list_resources, CHECKLIST, QUESTIONS
        category, q, profile = (request.args.get(key, '') for key in ('category', 'q', 'profile'))
        return jsonify(resources=list_resources(category, q, profile), checklist=CHECKLIST, questions=QUESTIONS,
                       progress=store.career_progress(g.user['id']))

    @app.put('/api/career/progress')
    def career_progress():
        from jobhunter.career_resources import validate_progress
        progress = validate_progress(request.get_json(silent=True))
        store.save_career_progress(g.user['id'], progress)
        return jsonify(ok=True)

    @app.post("/api/integrations/jooble")
    def jooble_key():
        body = request.get_json(silent=True) or {}
        code, key = body.get("country", ""), body.get("key", "")
        if code not in HOSTS or not isinstance(key, str) or not 10 <= len(key.strip()) <= 256 or not re.fullmatch(r"[A-Za-z0-9_-]+", key.strip()):
            raise ValueError("Selecione o país e informe uma chave Jooble válida para esse país.")
        name = "JOOBLE_API_KEY_" + code
        with configuration_lock:
            save_settings(store, BASE / '.env', {name: key.strip()})
        return jsonify(ok=True)

    @app.patch("/api/companies/<int:identifier>")
    def update_company(identifier):
        body = request.get_json(silent=True) or {}
        if not isinstance(body.get("enabled"), bool):
            raise ValueError("Informe se a empresa deve ficar ativa.")
        if not store.update_company(identifier, enabled=body['enabled'], user_id=g.user['id']):
            return jsonify(error='Empresa não encontrada.'), 404
        return jsonify(ok=True)

    @app.delete("/api/companies/<int:identifier>")
    def remove_company(identifier):
        if not store.update_company(identifier, remove=True, user_id=g.user['id']):
            return jsonify(error='Empresa não encontrada.'), 404
        return jsonify(ok=True)

    def execute_search(identifier, filters, companies, user_id):
        try:
            # No Vercel o trabalho termina antes de responder; o Neon guarda seu resultado.
            with http.deadline(240 if serverless else None):
                result = providers.run_search(filters, companies, usage=usage, user_id=user_id)
            store.finish_search(identifier, result, user_id=user_id)
        except Exception as exc:
            store.finish_search(identifier, {"error": f"A busca falhou ({type(exc).__name__}). Tente novamente."}, 'error', user_id=user_id)
        finally:
            search_slots.release()

    @app.post("/api/search")
    def search():
        companies = store.companies(g.user['id'])
        filters = validate_filters(request.get_json(silent=True), companies)
        if not store.rate_limit(f'search:{g.user["id"]}', 20, 3600):
            return jsonify(error='Limite de 20 buscas por hora atingido para sua conta.'), 429
        if not search_slots.acquire(blocking=False):
            return jsonify(error="Já há duas buscas em andamento. Aguarde uma delas terminar."), 429
        identifier = uuid.uuid4().hex
        try:
            store.start_search(identifier, filters, g.user['id'])
            if not serverless:
                executor.submit(execute_search, identifier, filters, companies, g.user['id'])
        except Exception:
            search_slots.release()
            raise
        if serverless:
            execute_search(identifier, filters, companies, g.user['id'])
        return jsonify(id=identifier, status="running"), 202

    @app.get("/api/search/<identifier>")
    def get_search(identifier):
        if serverless:
            store.expire_searches(g.user['id'])
        found = store.search(identifier, g.user['id'])
        return jsonify(found) if found else (jsonify(error="Busca não encontrada."), 404)

    @app.get("/api/searches")
    def searches():
        if serverless:
            store.expire_searches(g.user['id'])
        return jsonify(searches=store.recent_searches(g.user['id']))

    @app.get("/api/search/<identifier>/grounding")
    def grounding_suggestions(identifier):
        found = store.search(identifier, g.user['id'])
        if not found:
            return jsonify(error='Busca não encontrada.'), 404
        content = found.get('search_suggestions', '')
        response = app.response_class(content, mimetype="text/html")
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; frame-ancestors 'self'; sandbox allow-popups allow-popups-to-escape-sandbox"
        return response

    @app.get("/api/favorites")
    def favorites():
        return jsonify(jobs=store.favorites(g.user['id']))

    @app.get('/api/jobs')
    def found_jobs():
        status = request.args.get('status', 'all')
        try:
            offset = int(request.args.get('offset', '0'))
        except ValueError:
            raise ValueError('Página de vagas inválida.') from None
        if status not in {'all', 'eligible', 'review'} or not 0 <= offset <= 500000:
            raise ValueError('Filtro ou página de vagas inválidos.')
        return jsonify(**store.found_jobs(g.user['id'], status=status, offset=offset))

    def find_job(identifier, search_id):
        if not isinstance(identifier, str) or not identifier or not isinstance(search_id, str):
            return None
        search = store.search(search_id, g.user['id']) or {}
        jobs = search.get('jobs', []) + search.get('review_jobs', []) + store.favorites(g.user['id'])
        found = next((job for job in jobs if job["id"] == identifier), None)
        # Sem uma busca específica, a lista consolidada também permite salvar a vaga.
        return found or (store.indexed_job(identifier, g.user['id']) if not search_id else None)

    @app.post("/api/favorites")
    def add_favorite():
        body = request.get_json(silent=True) or {}
        job = find_job(body.get("id"), body.get("search_id", ""))
        if not job:
            raise ValueError("Vaga não encontrada nos resultados da busca.")
        store.favorite(job, user_id=g.user['id'])
        return jsonify(ok=True)

    @app.delete("/api/favorites/<identifier>")
    def remove_favorite(identifier):
        store.favorite({'id': identifier}, remove=True, user_id=g.user['id'])
        return jsonify(ok=True)

    @app.post("/api/notify")
    def notify():
        body = request.get_json(silent=True) or {}
        ids, channels = body.get("ids", []), body.get("channels", [])
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_NOTIFY_JOBS or any(not isinstance(item, str) for item in ids):
            raise ValueError(f'Selecione de 1 a {MAX_NOTIFY_JOBS} vagas para enviar.')
        if not isinstance(channels, list) or not channels or any(item not in {"telegram", "email"} for item in channels):
            raise ValueError("Selecione Telegram ou e-mail.")
        if serverless and 'telegram' in channels and len(ids) > 1:
            raise ValueError('Na interface pública, envie o Telegram em lotes de uma vaga. O painel divide sua seleção automaticamente.')
        jobs = [find_job(identifier, body.get("search_id", "")) for identifier in dict.fromkeys(ids)]
        if any(job is None for job in jobs):
            raise ValueError("Uma das vagas não foi encontrada.")
        search_filters = (store.search(body.get('search_id', ''), g.user['id']) or {}).get('filters', g.user['preferences'])
        minimum = max(0 if search_filters.get('profile') == 'custom' else 7000, search_filters.get('salary_min', 7000))
        if any(not matching.assess(job, search_filters.get("profile", "both"), search_filters.get("keywords", []),
                                   search_filters.get("strict_title", True), search_filters.get("excluded", []))["matched"] for job in jobs):
            raise ValueError("Uma das vagas não atende ao perfil de engenharia selecionado. Atualize a busca antes de enviar.")
        if any(salary.evaluate(job, minimum)["status"] != "eligible" for job in jobs):
            raise ValueError("Alertas aceitam apenas vagas com salário publicado que atenda ao mínimo. Vagas para análise podem ser salvas.")
        reports = []
        with delivery_lock:
            for channel in dict.fromkeys(channels):
                selected = [job for job in jobs if not store.delivered(job['id'], channel, g.user['id'])]
                if not selected:
                    reports.append({"channel": channel, "status": "ok", "sent": 0, "note": "As vagas selecionadas já foram enviadas por este canal."})
                    continue
                sent = 0
                try:
                    if channel == "telegram":
                        token, chat_id = main.required_env('TELEGRAM_BOT_TOKEN'), contacts_for(g.user).get('telegram_chat_id')
                        if not chat_id:
                            raise ValueError('Cadastre seu chat Telegram em Meu perfil.')
                        for identifiers, parts in main.telegram_batches([(job["id"], job) for job in selected]):
                            telegram_pacer.send(main.send_telegram, token, chat_id, '<b>Bot Hunter · oportunidades globais</b>\n\n' + '\n\n'.join(parts))
                            store.mark_delivered(identifiers, channel, g.user['id'])
                            sent += len(identifiers)
                    else:
                        recipient = contacts_for(g.user).get('email_to')
                        if not recipient:
                            raise ValueError('Cadastre seu e-mail de alertas em Meu perfil.')
                        settings = main.email_settings(recipient)
                        if os.getenv('EMAIL_DELIVERY_MODE') == 'queue':
                            from jobhunter.email_queue import EmailQueue
                            if not store.rate_limit(f'email-queue:{g.user["id"]}', 5, 86400):
                                raise ValueError('Limite de cinco lotes de e-mail por dia atingido.')
                            count = EmailQueue(store).enqueue(g.user['id'], recipient, selected)
                            reports.append({'channel': 'email', 'status': 'queued', 'sent': 0, 'queued': count,
                                            'note': f'{count} vagas na fila Gmail. O Actions envia em dias úteis; acompanhe em Meu perfil.'})
                            continue
                        main.send_email(settings, selected)
                        store.mark_delivered([job['id'] for job in selected], channel, g.user['id'])
                        sent = len(selected)
                    reports.append({"channel": channel, "status": "ok", "sent": sent})
                except Exception as exc:
                    reports.append({"channel": channel, "status": "error", "sent": sent,
                                    "note": f"Falha no envio ({type(exc).__name__}). Confira as credenciais do canal."})
        return jsonify(reports=reports)

    @app.get('/api/email-queue')
    def email_queue_status():
        from jobhunter.email_queue import EmailQueue
        return jsonify(batches=EmailQueue(store).status(g.user['id']))

    @app.post('/api/email-queue/<identifier>/retry')
    def email_queue_retry(identifier):
        from jobhunter.email_queue import EmailQueue
        if not EmailQueue(store).retry(identifier, g.user['id']):
            raise ValueError('Este envio não pode ser repetido ou já atingiu três tentativas.')
        return jsonify(ok=True)

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bot Hunter · interface web local")
    parser.add_argument("--port", type=int, default=5000)
    arguments = parser.parse_args()
    create_app().run(host="127.0.0.1", port=arguments.port, debug=False, threaded=True)
