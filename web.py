"""Interface local: python web.py. O bot de linha de comando continua em main.py."""
import argparse
import hmac
import os
import re
import secrets
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import set_key
from flask import Flask, jsonify, render_template, request, send_from_directory

import main
from jobhunter import geo, providers, salary, matching
from jobhunter.storage import Store
from jobhunter.jooble_markets import MARKETS, HOSTS

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
    if not isinstance(sources, list) or not sources or any(item not in {"companies", "google", "jooble", "gemini"} for item in sources):
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
    if profile not in {"product", "production", "both", "custom"}:
        raise ValueError("Escolha um perfil de engenharia válido.")
    minimum = body.get("salary_min", 7000)
    if type(minimum) not in (int, float) or not 7000 <= minimum <= 1000000:
        raise ValueError("O salário mínimo deve ser de R$ 7.000 a R$ 1.000.000 por mês.")
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
    csrf = secrets.token_urlsafe(32)
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hunter")
    app.extensions["executor"] = executor
    search_slots = threading.BoundedSemaphore(2)
    delivery_lock = threading.Lock()
    configuration_lock = threading.Lock()

    @app.before_request
    def protect_mutations():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if not hmac.compare_digest(request.headers.get("X-Hunter-CSRF", ""), csrf):
                return jsonify(error="Atualize a página antes de continuar."), 403
            if request.headers.get("Origin") and urlsplit(request.headers["Origin"]).netloc != request.host:
                return jsonify(error="Origem da requisição inválida."), 403

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if not request.path.endswith("/grounding"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'"
        if request.path.startswith("/api"):
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
        return render_template("index.html", csrf=csrf)

    @app.get("/assets/<path:filename>")
    def assets(filename):
        return send_from_directory(BASE / "assets", filename)

    @app.get("/api/config")
    def config():
        def configured(name):
            value = os.getenv(name, "").strip()
            return bool(value) and not value.startswith("COLE_")
        return jsonify(regions=[{"code": code, "name": name} for code, name in geo.REGIONS.items()],
                       countries=geo.COUNTRIES, companies=store.companies(),
                       jooble_countries=list(providers.jooble_keys()), jooble_markets=MARKETS,
                       integrations={"jooble": bool(providers.jooble_keys()), "google": configured("SERPAPI_API_KEY"), "gemini": configured("GEMINI_API_KEY"),
                                     "telegram": configured("TELEGRAM_BOT_TOKEN") and configured("TELEGRAM_CHAT_ID"),
                                     "email": all(configured(key) for key in ("EMAIL_FROM", "EMAIL_TO", "EMAIL_APP_PASSWORD"))},
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
        if len(store.companies()) >= 10:
            raise ValueError("O limite local é de 10 empresas por enquanto.")
        try:
            company = providers.discover_company(name.strip(), url)
        except (providers.requests.RequestException, OSError):
            raise ValueError("Não foi possível acessar esse site. Confira a URL da página de carreiras.") from None
        identifier = store.add_company(company)
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
        store.update_company(identifier, enabled=body["enabled"])
        return jsonify(ok=True)

    @app.delete("/api/companies/<int:identifier>")
    def remove_company(identifier):
        store.update_company(identifier, remove=True)
        return jsonify(ok=True)

    def execute_search(identifier, filters, companies):
        try:
            store.finish_search(identifier, providers.run_search(filters, companies))
        except Exception as exc:
            store.finish_search(identifier, {"error": f"A busca falhou ({type(exc).__name__}). Tente novamente."}, "error")
        finally:
            search_slots.release()

    @app.post("/api/search")
    def search():
        companies = store.companies()
        filters = validate_filters(request.get_json(silent=True), companies)
        if not search_slots.acquire(blocking=False):
            return jsonify(error="Já há duas buscas em andamento. Aguarde uma delas terminar."), 429
        identifier = uuid.uuid4().hex
        try:
            store.start_search(identifier, filters)
            executor.submit(execute_search, identifier, filters, companies)
        except Exception:
            search_slots.release()
            raise
        return jsonify(id=identifier, status="running"), 202

    @app.get("/api/search/<identifier>")
    def get_search(identifier):
        found = store.search(identifier)
        return jsonify(found) if found else (jsonify(error="Busca não encontrada."), 404)

    @app.get("/api/searches")
    def searches():
        return jsonify(searches=store.recent_searches())

    @app.get("/api/search/<identifier>/grounding")
    def grounding_suggestions(identifier):
        content = (store.search(identifier) or {}).get("search_suggestions", "")
        response = app.response_class(content, mimetype="text/html")
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; frame-ancestors 'self'; sandbox allow-popups allow-popups-to-escape-sandbox"
        return response

    @app.get("/api/favorites")
    def favorites():
        return jsonify(jobs=store.favorites())

    def find_job(identifier, search_id):
        search = store.search(search_id) or {}
        jobs = search.get("jobs", []) + search.get("review_jobs", []) + store.favorites()
        return next((job for job in jobs if job["id"] == identifier), None)

    @app.post("/api/favorites")
    def add_favorite():
        body = request.get_json(silent=True) or {}
        job = find_job(body.get("id"), body.get("search_id", ""))
        if not job:
            raise ValueError("Vaga não encontrada nos resultados da busca.")
        store.favorite(job)
        return jsonify(ok=True)

    @app.delete("/api/favorites/<identifier>")
    def remove_favorite(identifier):
        store.favorite({"id": identifier}, remove=True)
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
        search_filters = (store.search(body.get("search_id", "")) or {}).get("filters", {})
        minimum = max(7000, search_filters.get("salary_min", 7000))
        if any(not matching.assess(job, search_filters.get("profile", "both"), search_filters.get("keywords", []),
                                   search_filters.get("strict_title", True), search_filters.get("excluded", []))["matched"] for job in jobs):
            raise ValueError("Uma das vagas não atende ao perfil de engenharia selecionado. Atualize a busca antes de enviar.")
        if any(salary.evaluate(job, minimum)["status"] != "eligible" for job in jobs):
            raise ValueError("Alertas aceitam apenas vagas com salário publicado que atenda ao mínimo. Vagas para análise podem ser salvas.")
        reports = []
        with delivery_lock:
            for channel in dict.fromkeys(channels):
                selected = [job for job in jobs if not store.delivered(job["id"], channel)]
                if not selected:
                    reports.append({"channel": channel, "status": "ok", "sent": 0, "note": "As vagas selecionadas já foram enviadas por este canal."})
                    continue
                sent = 0
                try:
                    if channel == "telegram":
                        token, chat_id = main.required_env("TELEGRAM_BOT_TOKEN"), main.required_env("TELEGRAM_CHAT_ID")
                        for identifiers, parts in main.telegram_batches([(job["id"], job) for job in selected]):
                            main.send_telegram(token, chat_id, "<b>Bot Hunter · oportunidades globais</b>\n\n" + "\n\n".join(parts))
                            store.mark_delivered(identifiers, channel)
                            sent += len(identifiers)
                    else:
                        main.send_email(main.email_settings(), selected)
                        store.mark_delivered([job["id"] for job in selected], channel)
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
