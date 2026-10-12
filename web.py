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

from dotenv import set_key
from flask import Flask, g, jsonify, render_template, request, send_from_directory, session

import main
from jobhunter import geo, providers, salary, matching
from jobhunter.storage import Store
from jobhunter.jooble_markets import MARKETS, HOSTS
from jobhunter.auth import configure_auth, contacts_for, public_user

BASE = Path(__file__).resolve().parent


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
    sources = body.get("sources", ["companies"])
    if not isinstance(sources, list) or not sources or any(not isinstance(item, str) or item not in {"companies", "google", "jooble", "gemini"} for item in sources):
        raise ValueError("Selecione pelo menos uma fonte válida.")
    company_ids = body.get("company_ids", [company["id"] for company in companies if company["enabled"]])
    if not isinstance(company_ids, list) or any(type(item) is not int for item in company_ids):
        raise ValueError("Selecione empresas válidas.")
    valid_ids = {company["id"] for company in companies if company["enabled"]}
    if any(item not in valid_ids for item in company_ids):
        raise ValueError("Uma das empresas selecionadas está desativada ou não existe.")
    if "companies" in sources and not company_ids:
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
    for key in ("strict_title", "remote", "multilingual"):
        if key in body and not isinstance(body[key], bool):
            raise ValueError("As opções de cargo e remoto precisam ser true ou false.")
    profile = body.get("profile", "both")
    if not isinstance(profile, str) or profile not in {"product", "production", "both", "custom"}:
        raise ValueError("Escolha um perfil de engenharia válido.")
    minimum = body.get("salary_min", 7000)
    floor = 0 if profile == 'custom' else 7000
    if type(minimum) not in (int, float) or not floor <= minimum <= 1000000:
        raise ValueError(f'O salário mínimo deve ser de R$ {floor:,.0f} a R$ 1.000.000 por mês.')
    return {"keywords": keywords, "region": region, "country": country, "state": state,
            "city": city.strip(), "sources": list(dict.fromkeys(sources)), "company_ids": company_ids,
            "strict_title": body.get("strict_title", True), "remote": body.get("remote", False),
            "pages": pages, "excluded": main.split_terms(excluded), "profile": profile,
            "multilingual": body.get("multilingual", True), "salary_min": minimum}


def create_app(db_path=None):
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=100_000, JSON_SORT_KEYS=False)
    app.json.ensure_ascii = False
    store = Store(db_path or BASE / "data" / "hunter.sqlite")
    app.extensions["store"] = store
    configure_auth(app, store)
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hunter")
    app.extensions["executor"] = executor
    search_slots = threading.BoundedSemaphore(2)
    delivery_lock = threading.Lock()
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

    @app.get("/assets/<path:filename>")
    def assets(filename):
        return send_from_directory(BASE / "assets", filename)

    @app.get("/api/config")
    def config():
        def configured(name):
            value = os.getenv(name, "").strip()
            return bool(value) and not value.startswith("COLE_")
        return jsonify(regions=[{"code": code, "name": name} for code, name in geo.REGIONS.items()],
                       countries=geo.COUNTRIES, companies=store.companies(g.user['id']), user=public_user(g.user),
                       preferences=g.user['preferences'],
                       jooble_countries=list(providers.jooble_keys()), jooble_markets=MARKETS,
                       integrations={"jooble": bool(providers.jooble_keys()), "google": configured("SERPAPI_API_KEY"), "gemini": configured("GEMINI_API_KEY"),
                                     "telegram": configured("TELEGRAM_BOT_TOKEN") and bool(contacts_for(g.user).get('telegram_chat_id')),
                                     "email": all(configured(key) for key in ("EMAIL_FROM", "EMAIL_APP_PASSWORD")) and bool(contacts_for(g.user).get('email_to'))},
                       defaults={"keywords": "product engineer;production engineer;engenheiro de produto", "sources": ["companies"],
                                 "salary_min": 7000, "profile": "both"})

    @app.post("/api/integrations/gemini")
    def gemini_key():
        body = request.get_json(silent=True) or {}
        key = body.get("key", "")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{20,256}", key.strip()):
            raise ValueError("Informe uma chave Gemini válida do Google AI Studio.")
        with configuration_lock:
            set_key(str(BASE / ".env"), "GEMINI_API_KEY", key.strip(), quote_mode="never")
            os.environ["GEMINI_API_KEY"] = key.strip()
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
        store.update_user(g.user['id'], name=name.strip(), contacts={'email_to': email.strip(), 'telegram_chat_id': chat.strip()})
        return jsonify(ok=True)

    @app.post('/api/preferences')
    def save_preferences():
        filters = validate_filters(request.get_json(silent=True), store.companies(g.user['id']))
        store.update_user(g.user['id'], preferences=filters)
        return jsonify(ok=True, preferences=filters)

    @app.post('/api/companies/discover')
    def discover_companies():
        from jobhunter.discovery import suggest_companies
        filters = validate_filters(request.get_json(silent=True), store.companies(g.user['id']))
        if not store.rate_limit(f'discovery:{g.user["id"]}', 5, 3600):
            return jsonify(error='Limite de cinco descobertas de empresas por hora atingido.'), 429
        if not search_slots.acquire(blocking=False):
            return jsonify(error='Há pesquisas em andamento. Aguarde antes de descobrir empresas.'), 429
        try:
            result = suggest_companies(filters, store.companies(g.user['id']))
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
            set_key(str(BASE / ".env"), "SERPAPI_API_KEY", key, quote_mode="never")
            os.environ["SERPAPI_API_KEY"] = key
        return jsonify(ok=True)

    @app.post("/api/companies")
    def add_company():
        body = request.get_json(silent=True) or {}
        name, url = body.get("name", ""), body.get("url", "")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or not isinstance(url, str) or len(url) > 1000:
            raise ValueError("Informe o nome da empresa e sua página de carreiras.")
        if len(store.companies(g.user['id'])) >= 30:
            raise ValueError('O limite é de 30 empresas por usuário.')
        try:
            company = providers.discover_company(name.strip(), url)
        except (providers.requests.RequestException, OSError):
            raise ValueError("Não foi possível acessar esse site. Confira a URL da página de carreiras.") from None
        identifier = store.add_company(company, g.user['id'])
        return jsonify(id=identifier, **company), 201

    @app.post("/api/integrations/jooble")
    def jooble_key():
        body = request.get_json(silent=True) or {}
        code, key = body.get("country", ""), body.get("key", "")
        if code not in HOSTS or not isinstance(key, str) or not 10 <= len(key.strip()) <= 256 or not re.fullmatch(r"[A-Za-z0-9_-]+", key.strip()):
            raise ValueError("Selecione o país e informe uma chave Jooble válida para esse país.")
        name = "JOOBLE_API_KEY_" + code
        with configuration_lock:
            set_key(str(BASE / ".env"), name, key.strip(), quote_mode="never")
            os.environ[name] = key.strip()
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
            store.finish_search(identifier, providers.run_search(filters, companies), user_id=user_id)
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
            executor.submit(execute_search, identifier, filters, companies, g.user['id'])
        except Exception:
            search_slots.release()
            raise
        return jsonify(id=identifier, status="running"), 202

    @app.get("/api/search/<identifier>")
    def get_search(identifier):
        found = store.search(identifier, g.user['id'])
        return jsonify(found) if found else (jsonify(error="Busca não encontrada."), 404)

    @app.get("/api/searches")
    def searches():
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

    def find_job(identifier, search_id):
        search = store.search(search_id, g.user['id']) or {}
        jobs = search.get('jobs', []) + search.get('review_jobs', []) + store.favorites(g.user['id'])
        return next((job for job in jobs if job["id"] == identifier), None)

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
        if not isinstance(ids, list) or not 1 <= len(ids) <= 15 or any(not isinstance(item, str) for item in ids):
            raise ValueError("Selecione de 1 a 15 vagas para enviar.")
        if not isinstance(channels, list) or not channels or any(item not in {"telegram", "email"} for item in channels):
            raise ValueError("Selecione Telegram ou e-mail.")
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
                            main.send_telegram(token, chat_id, "<b>Bot Hunter · oportunidades globais</b>\n\n" + "\n\n".join(parts))
                            store.mark_delivered(identifiers, channel, g.user['id'])
                            sent += len(identifiers)
                    else:
                        recipient = contacts_for(g.user).get('email_to')
                        if not recipient:
                            raise ValueError('Cadastre seu e-mail de alertas em Meu perfil.')
                        settings = main.email_settings(recipient)
                        main.send_email(settings, selected)
                        store.mark_delivered([job['id'] for job in selected], channel, g.user['id'])
                        sent = len(selected)
                    reports.append({"channel": channel, "status": "ok", "sent": sent})
                except Exception as exc:
                    reports.append({"channel": channel, "status": "error", "sent": sent,
                                    "note": f"Falha no envio ({type(exc).__name__}). Confira as credenciais do canal."})
        return jsonify(reports=reports)

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bot Hunter · interface web local")
    parser.add_argument("--port", type=int, default=5000)
    arguments = parser.parse_args()
    create_app().run(host="127.0.0.1", port=arguments.port, debug=False, threaded=True)
