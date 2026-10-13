"""Fontes públicas de vagas. Sem login, scraping do Google ou execução de JS externo."""
import hashlib
import ipaddress
import json
import os
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from . import http
from bs4 import BeautifulSoup

import main
from .geo import BY_CODE, COUNTRIES, country_code, location_matches, state_names
from . import matching, salary
from .jooble_markets import HOSTS

USER_AGENT = "BotHunter/1.0 (personal career search)"


class NeedsConfiguration(RuntimeError):
    """Pendência de uma fonte que não invalida o resultado das outras."""


def jooble_keys():
    keys = {}
    base_code = os.getenv("JOOBLE_COUNTRY", "BR").upper()
    base_key = os.getenv("JOOBLE_API_KEY", "").strip()
    if base_code in BY_CODE and base_key and not base_key.startswith("COLE_"):
        keys[base_code] = base_key
    for code in HOSTS:
        key = os.getenv("JOOBLE_API_KEY_" + code, "").strip()
        if key and not key.startswith("COLE_"):
            keys[code] = key
    return keys


def jooble_host(code):
    if code not in HOSTS:
        raise NeedsConfiguration("A Jooble não divulga um domínio regional para este país. Use empresas ou Gemini para ampliar a busca.")
    return HOSTS[code]


def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Use uma URL pública de carreiras começando com https://.")
    if parts.port not in (None, 80, 443):
        raise ValueError("A página precisa usar uma porta HTTP padrão.")
    addresses = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Endereços locais ou privados não podem ser cadastrados.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def public_get(url, params=None):
    """Checa também redirecionamentos; limita downloads e não encaminha credenciais."""
    http.checkpoint()
    url = validate_url(url)
    for _ in range(5):
        response = http.get(url, params=params, timeout=(5, 20), allow_redirects=False,
                                stream=True, headers={"User-Agent": USER_AGENT})
        params = None
        if response.is_redirect:
            next_url = validate_url(urljoin(url, response.headers["Location"]))
            response.close()
            url = next_url
            continue
        try:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_content(65536):
                http.checkpoint()
                body.extend(chunk)
                if len(body) > 4_000_000:
                    raise ValueError("A página excedeu o tamanho permitido.")
            return bytes(body).decode(response.encoding or "utf-8", errors="replace")
        finally:
            response.close()
    raise ValueError("A página redirecionou muitas vezes.")


def public_json(url, params=None):
    return json.loads(public_get(url, params))


def detect_provider(url):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = [part for part in parts.path.split("/") if part]
    if host == "careers.bosch.com" or host == "jobs.bosch.com" or host == "www.bosch.com":
        return "smartrecruiters", "BoschGroup"
    if host in {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"} and path:
        return "smartrecruiters", path[0]
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io"} and path:
        return ("greenhouse_eu" if ".eu." in host else "greenhouse"), path[0]
    if host in {"jobs.lever.co", "jobs.eu.lever.co"} and path:
        return ("lever_eu" if ".eu." in host else "lever"), path[0]
    if host == 'jobs.ashbyhq.com' and path:
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,120}', path[0]):
            raise ValueError('Identificador Ashby inválido.')
        return 'ashby', path[0]
    return "website", ""


def robots_allows(url):
    parts = urlsplit(url)
    parser = RobotFileParser()
    robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
    try:
        parser.parse(public_get(robots_url).splitlines())
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return True
        return False
    except (requests.RequestException, ValueError, OSError):
        return False
    return parser.can_fetch(USER_AGENT, url)


def discover_company(name, url):
    url = validate_url(url.strip())
    provider, identifier = detect_provider(url)
    if provider == "website" and robots_allows(url):
        soup = BeautifulSoup(public_get(url), "html.parser")
        for element in soup.select("a[href], iframe[src], script[src]"):
            candidate = urljoin(url, element.get("href") or element.get("src") or "")
            detected, tenant = detect_provider(candidate)
            if detected != "website":
                provider, identifier = detected, tenant
                break
    if identifier and not re.fullmatch(r"[\w.-]{1,120}", identifier):
        raise ValueError("Identificador da plataforma de carreiras inválido.")
    return {"name": name, "url": url, "provider": provider, "identifier": identifier}


def safe_link(value):
    if not isinstance(value, str):
        return ""
    parts = urlsplit(value)
    return value if parts.scheme in {"https", "http"} and parts.hostname and not parts.username else ""


def clean_text(value):
    return BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)


def make_job(title, company, location, link, source, **extra):
    link = safe_link(link)
    code = country_code(extra.pop("country", ""))
    if not code:
        for part in reversed(re.split(r"[,|]", location or "")):
            part = part.strip()
            # "San Francisco, CA" não é Canadá; códigos de estado não são códigos de país em texto livre.
            if len(part) == 2 and part.upper() not in {"UK", "GB", "US"}:
                continue
            code = country_code(part)
            if code:
                break
    job = {"id": hashlib.sha256((link + "|" + code + "|" + matching.normalize(location)).encode()).hexdigest()[:24], "title": clean_text(title),
           "company": clean_text(company), "location": clean_text(location), "link": link,
           "source": source, "sources": [source], "country": code,
           "country_name": BY_CODE.get(code, {}).get("name", ""), "state": "", "city": "",
           "remote": False, "updated": "", "description": "", "salary": "", "employment": "", **extra}
    job["description"] = clean_text(job["description"])[:12000]
    return job


def smartrecruiters(company, filters):
    jobs, notes = [], []
    failed = 0
    for keyword in filters["keywords"]:
        for page in range(filters["pages"]):
            # SmartRecruiters amplia palavras separadas com OR. Aspas preservam o cargo como frase.
            query = '"' + keyword.replace('"', '') + '"' if " " in keyword else keyword
            params = {"q": query, "limit": 100, "offset": page * 100, "destination": "PUBLIC"}
            if filters["country"]:
                params["country"] = filters["country"].lower()
            if filters["city"]:
                params["city"] = filters["city"]
            if filters["remote"]:
                params["locationType"] = "REMOTE"
            try:
                data = public_json(f"https://api.smartrecruiters.com/v1/companies/{company['identifier']}/postings", params)
            except (requests.RequestException, ValueError, OSError):
                failed += 1
                break
            content = data.get("content", [])
            for item in content:
                loc = item.get("location") or {}
                link = item.get("applyUrl") or f"https://jobs.smartrecruiters.com/{company['identifier']}/{item['id']}"
                jobs.append(make_job(item.get("name"), item.get("company", {}).get("name") or company["name"],
                                     loc.get("fullLocation") or ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")])),
                                     link, company["name"], country=loc.get("country"), state=loc.get("region", ""),
                                     city=loc.get("city", ""), remote=bool(loc.get("remote")),
                                     updated=item.get("releasedDate", ""), employment=item.get("typeOfEmployment", {}).get("label", ""),
                                     detail_url=f"https://api.smartrecruiters.com/v1/companies/{company['identifier']}/postings/{item['id']}"))
            if len(content) < 100 or (page + 1) * 100 >= data.get("totalFound", 0):
                break
            if page == filters["pages"] - 1:
                notes.append("Há mais vagas nesta empresa. Aumente o número de páginas ou refine os filtros.")
    if failed:
        notes.append(f"{failed} consultas falharam; resultados das consultas bem-sucedidas foram mantidos.")
        if not jobs and failed == len(filters["keywords"]):
            raise RuntimeError("Todas as consultas desta empresa falharam.")
    return jobs, list(dict.fromkeys(notes))


def greenhouse(company, filters):
    domain = "boards-api.eu.greenhouse.io" if company["provider"] == "greenhouse_eu" else "boards-api.greenhouse.io"
    data = public_json(f"https://{domain}/v1/boards/{company['identifier']}/jobs", {"content": "false"})
    return [make_job(item["title"], company["name"], item.get("location", {}).get("name", ""),
                     item.get("absolute_url", ""), company["name"], updated=item.get("updated_at", ""),
                     description=item.get("content", ""), remote="remote" in main.normalize(item.get("location", {}).get("name", "")))
            for item in data.get("jobs", [])], []


def lever(company, filters):
    domain = "api.eu.lever.co" if company["provider"] == "lever_eu" else "api.lever.co"
    jobs = []
    for page in range(filters["pages"]):
        data = public_json(f"https://{domain}/v0/postings/{company['identifier']}", {"mode": "json", "limit": 100, "skip": page * 100})
        for item in data:
            categories = item.get("categories", {})
            jobs.append(make_job(item.get("text"), company["name"], categories.get("location", ""),
                                 item.get("hostedUrl") or item.get("applyUrl"), company["name"],
                                 description=item.get("descriptionPlain", ""), employment=categories.get("commitment", ""),
                                 remote=item.get("workplaceType") == "remote", country=item.get("country", ""),
                                 salary_data=salary.provider_salary(item.get("salaryRange")),
                                 salary=salary.salary_label(salary.provider_salary(item.get("salaryRange")))))
        if len(data) < 100:
            return jobs, []
    return jobs, ["Consulta limitada às páginas selecionadas."]


def ashby_salary(compensation):
    """Remuneração base publicada; bônus e participação nunca contam como salário."""
    if not isinstance(compensation, dict):
        return {}
    components = compensation.get('summaryComponents', [])
    if not isinstance(components, list):
        return {}
    salaries = [item for item in components if isinstance(item, dict) and item.get('compensationType') == 'Salary' and item.get('minValue') is not None]
    if len(salaries) != 1:
        # Faixas para localidades distintas não identificadas precisam de análise humana.
        return {}
    item = salaries[0]
    if re.search(r'\b(estimated|estimate|estimado)\b', matching.normalize(str(item.get('summary', '')) + ' ' + str(compensation.get('compensationTierSummary', '')))):
        return {}
    period = {'1 YEAR': 'YEAR', '1 MONTH': 'MONTH', '1 WEEK': 'WEEK', '1 HOUR': 'HOUR'}.get(item.get('interval'), '')
    return {'min': item['minValue'], 'max': item.get('maxValue'), 'currency': item.get('currencyCode', ''), 'period': period}


def ashby(company, filters):
    tenant = company['identifier']
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,120}', tenant):
        raise ValueError('Identificador Ashby inválido.')
    data = public_json(f'https://api.ashbyhq.com/posting-api/job-board/{tenant}', {'includeCompensation': 'true'})
    if not isinstance(data, dict) or not isinstance(data.get('jobs'), list):
        raise ValueError('Resposta Ashby sem lista de anúncios.')
    jobs = []
    for item in data['jobs']:
        http.checkpoint()
        if not isinstance(item, dict) or item.get('isListed') is not True:
            continue
        link = safe_link(item.get('applyUrl')) or safe_link(item.get('jobUrl'))
        if not link or not isinstance(item.get('title'), str):
            continue
        address = item.get('address')
        loc = address.get('postalAddress', {}) if isinstance(address, dict) else {}
        pay = ashby_salary(item.get('compensation'))
        # Cada localidade real ganha sua própria identidade e passa pelos filtros comuns.
        locations = [(item.get('location', ''), loc)]
        secondary = item.get('secondaryLocations') or []
        for extra in secondary if isinstance(secondary, list) else []:
            if isinstance(extra, dict) and isinstance(extra.get('address'), dict):
                locations.append((extra.get('location', ''), extra['address']))
        for label, address in locations:
            if not isinstance(address, dict):
                address = {}
            location = label or ', '.join(str(address.get(key) or '') for key in ('addressLocality', 'addressRegion', 'addressCountry')).strip(', ')
            jobs.append(make_job(item['title'], company['name'], location, link, company['name'],
                                country=address.get('addressCountry', ''), city=address.get('addressLocality', ''), state=address.get('addressRegion', ''),
                                remote=item.get('isRemote') is True or item.get('workplaceType') == 'Remote',
                                employment=item.get('employmentType', ''), updated=item.get('publishedAt', ''),
                                description=item.get('descriptionPlain') or item.get('descriptionHtml', ''),
                                salary_data=pay, salary=salary.salary_label(pay)))
    return jobs, ['Board Ashby consultado uma vez; cargos e localidades são filtrados no Bot Hunter. Remoto não implica contratação em qualquer país.']


def company_search_limit():
    try:
        return min(20, max(1, int(os.getenv('COMPANY_SEARCH_LIMIT', '10'))))
    except ValueError:
        return 10


def fetch_company_jobs(company, filters, usage=None):
    """Cache público de 12 horas, sem gastar cotas dos agregadores ou da IA."""
    adapter = COMPANY_PROVIDERS[company['provider']]
    query = {'version': 1, 'provider': company['provider'], 'identifier': company.get('identifier', ''), 'url': company.get('url', '')}
    if company['provider'] not in {'ashby', 'greenhouse', 'greenhouse_eu'}:
        query.update({key: filters.get(key) for key in ('keywords', 'pages', 'country', 'city', 'remote')})
    if company['provider'] == 'smartrecruiters':
        query.update({key: filters.get(key) for key in ('profile', 'state', 'strict_title', 'excluded')})
    query['name'] = company['name']
    key = 'public-company-board'
    cached = usage.cached(key, query) if usage else None
    if cached is not None:
        return cached['jobs'], cached['notes'] + ['Resultados reaproveitados do cache de 12 horas; nenhuma nova consulta ao ATS.']
    if filters.get('_cache_only'):
        raise NeedsConfiguration('Não há resultados em cache para esta empresa.')
    jobs, notes = adapter(company, filters)
    jobs, details = enrich_company_jobs(company, jobs, filters)
    notes += details
    if usage:
        usage.remember(key, query, {'jobs': jobs, 'notes': notes}, ttl=43200)
    return jobs, notes + ['Nova consulta ao portal público; sem uso de Jooble, SerpAPI ou Gemini nesta fonte.']


def jobposting_nodes(value):
    if isinstance(value, list):
        for child in value:
            yield from jobposting_nodes(child)
    elif isinstance(value, dict):
        node_type = value.get("@type", "")
        if node_type == "JobPosting" or isinstance(node_type, list) and "JobPosting" in node_type:
            yield value
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                yield from jobposting_nodes(child)


def extract_jobpostings(html, url, company):
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        for item in jobposting_nodes(data):
            expiry = item.get("validThrough", "")
            if expiry:
                try:
                    if datetime.fromisoformat(expiry.replace("Z", "+00:00")).date() < datetime.now(timezone.utc).date():
                        continue
                except (ValueError, TypeError):
                    pass
            places = item.get("jobLocation") or [{}]
            if not isinstance(places, list):
                places = [places]
            for place in places:
                address = place.get("address", {}) if isinstance(place, dict) else {}
                if not isinstance(address, dict):
                    address = {}
                code = country_code(address.get("addressCountry"))
                loc = ", ".join(filter(None, [address.get("addressLocality"), address.get("addressRegion"), BY_CODE.get(code, {}).get("name")]))
                remote = item.get("jobLocationType") == "TELECOMMUTE"
                jobs.append(make_job(item.get("title"), (item.get("hiringOrganization") or {}).get("name") or company,
                                     loc or ("Remoto · localização não informada" if remote else "Localização não informada"),
                                     urljoin(url, item.get("url") or url), company, country=code,
                                     state=address.get("addressRegion", ""), city=address.get("addressLocality", ""),
                                     remote=remote, updated=item.get("datePosted", ""), description=item.get("description", ""),
                                     employment=str(item.get("employmentType", "")), salary_data=salary.schema_salary(item),
                                     salary=clean_text(json.dumps(item.get("baseSalary"), ensure_ascii=False)) if item.get("baseSalary") else ""))
    return jobs, soup


def website(company, filters):
    root = company["url"]
    if not robots_allows(root):
        return [], ["O site não permite a consulta automática ou não foi possível verificar robots.txt."]
    body = public_get(root)
    jobs, soup = extract_jobpostings(body, root, company["name"])
    # Nunca segue páginas de login ou navega recursivamente sem limite.
    links = []
    for anchor in soup.select("a[href]"):
        candidate = urljoin(root, anchor["href"])
        if (urlsplit(candidate).hostname == urlsplit(root).hostname and candidate != root
                and re.search(r"job|career|vaga|position|stelle", candidate, re.I) and candidate not in links):
            links.append(candidate)
    for link in links[:min(filters["pages"] * 3, 9)]:
        if robots_allows(link):
            try:
                found, _ = extract_jobpostings(public_get(link), link, company["name"])
                jobs.extend(found)
            except (requests.RequestException, ValueError, OSError):
                continue
    notes = ["Leitura limitada à página cadastrada e até 9 links públicos com dados JobPosting."]
    if not jobs:
        notes.append("Nenhuma vaga estruturada encontrada. Cadastre a página de vagas ou o endereço SmartRecruiters, Greenhouse ou Lever da empresa.")
    return jobs, notes


def market_codes(filters):
    if filters["country"]:
        return [filters["country"]]
    # Consultas por país são limitadas e selecionadas explicitamente; não fingimos cobertura exaustiva.
    codes = [item["code"] for item in COUNTRIES if not filters["region"] or item["region"] == filters["region"]]
    preferred = ["BR", "US", "DE", "IN", "JP", "AU", "CA", "GB", "FR", "MX", "CN", "ZA", "SG", "AE"]
    return [code for code in preferred if code in codes] + [code for code in codes if code not in preferred]


def query_location(filters, code):
    return ", ".join(filter(None, [filters["city"], next(iter(state_names(filters["state"])), ""), BY_CODE[code]["english"]]))


def jooble(filters, usage=None, user_id=0):
    if filters.get("country") and filters["country"] not in HOSTS:
        raise NeedsConfiguration("Este país não está na lista de mercados divulgados pela Jooble. Use empresas ou Gemini / Google Search.")
    keys = jooble_keys()
    jobs = []
    codes = market_codes(filters)
    available = [code for code in codes if code in keys]
    if not available:
        destination = BY_CODE[filters["country"]]["name"] if filters["country"] else "esta região"
        raise NeedsConfiguration("A Jooble exige uma chave por país. Cadastre a chave de " + destination + " em Integrações.")
    if usage and not filters.get('country'):
        available = usage.rank_markets(user_id, available, keys)
    try:
        budget = max(1, min(int(os.getenv("WEB_MAX_MARKET_QUERIES", "6")), 24))
    except ValueError:
        budget = 6
    markets = available[:max(1, budget // len(filters["keywords"]))]
    errors = []
    used = 0
    cached_count = 0
    consulted = []
    for code in markets:
        for keyword in filters["keywords"]:
            if used >= budget:
                break
            query = {"keywords": keyword, "location": query_location(filters, code),
                     "page": 1, "ResultOnPage": filters.get('jooble_count', 100), "radius": "0"}
            results = usage.cached(keys[code], query) if usage else None
            try:
                if results is None:
                    http.checkpoint()
                    if filters.get('_cache_only'):
                        filters['_budget_limited'] = True
                        continue
                    if usage:
                        from .usage import BudgetExceeded
                        try:
                            usage.reserve(user_id, code, keys[code])
                        except BudgetExceeded as exc:
                            filters['_budget_limited'] = True
                            errors.append(str(exc))
                            continue
                    used += 1
                    response = http.post("https://" + jooble_host(code) + "/api/" + keys[code], json=query, timeout=25)
                    if usage and response.status_code == 429:
                        try:
                            retry = int(response.headers.get('Retry-After', '3600'))
                        except ValueError:
                            retry = 3600
                        usage.block(keys[code], seconds=retry)
                    if usage and response.status_code in {400, 402, 403}:
                        # Só a confirmação do provedor indica esgotamento; chave inválida não significa saldo gasto.
                        message = response.text[:2000].casefold()
                        if any(term in message for term in ('quota exceeded', 'limit exceeded', 'no requests left', 'requests exhausted')):
                            usage.block(keys[code], exhausted=True)
                    response.raise_for_status()
                    results = response.json().get("jobs", [])
                    if usage:
                        usage.remember(keys[code], query, results)
                else:
                    cached_count += 1
                if code not in consulted:
                    consulted.append(code)
            except (requests.RequestException, ValueError) as exc:
                errors.append(BY_CODE[code]["name"] + ": consulta falhou (" + type(exc).__name__ + "). Confira a chave regional e a cota.")
                continue
            for item in results:
                # A API usa a localidade da consulta; quando a resposta não informa o país, registramos essa origem.
                loc = item.get("location", "")
                job = make_job(item.get("title"), item.get("company"), loc, item.get("link"), "Jooble",
                               salary=item.get("salary", ""), updated=item.get("updated", ""), description=item.get("snippet", ""),
                               remote=bool(re.search(r"\b(remote|remoto|home office)\b", main.normalize(loc))))
                if not job["country"]:
                    job.update(country=code, country_name=BY_CODE[code]["name"], country_basis="consulta")
                jobs.append(job)
    notes = ["Jooble: primeira página por cargo e país; país inferido da consulta quando ausente no anúncio.",
             f"Até {filters.get('jooble_count', 100)} anúncios por consulta; a API pode retornar menos. O limite de chamadas da busca permanece o mesmo.",
             "Consultados " + (", ".join(BY_CODE[code]["name"] for code in consulted) or "nenhum país nesta busca") + ". A Jooble exige uma chave própria para cada país.",
             f"{used} chamadas novas; {cached_count} consultas reaproveitadas do cache de 24 horas."] + list(dict.fromkeys(errors))
    if len(markets) < len(codes):
        notes.append("Outros países dependem de suas chaves regionais e do limite de consultas.")
    if errors and len(errors) == used and not usage:
        raise RuntimeError("Todas as consultas da Jooble falharam.")
    return jobs, notes


def google_url(filters):
    where = query_location(filters, filters["country"]) if filters["country"] else {"AF": "Africa", "AM": "Americas", "AS": "Asia", "EU": "Europe", "OC": "Oceania", "AN": "Antarctica"}.get(filters["region"], "worldwide")
    query = " OR ".join(filters["keywords"]) + " jobs " + where
    return "https://www.google.com/search?" + urlencode({"q": query, "udm": "8"})


def google_jobs(filters, usage=None, user_id=0):
    key = main.required_env("SERPAPI_API_KEY")
    jobs = []
    notes = []
    from .google_usage import GoogleBudget
    from .usage import BudgetExceeded
    budget = GoogleBudget(usage) if usage else None
    codes = market_codes(filters)
    # Google Empregos é uma busca localizada: em região/mundo consultamos até dois mercados por execução.
    for code in codes[:2]:
        for keyword in filters["keywords"]:
            next_token = ""
            for page in range(filters["pages"]):
                params = {"engine": "google_jobs", "q": keyword + " jobs in " + query_location(filters, code),
                          "gl": "uk" if code == "GB" else code.lower(), "hl": "pt" if code == "BR" else "en", "api_key": key}
                if next_token:
                    params["next_page_token"] = next_token
                # Não usamos public_get aqui: a chave vai apenas para o domínio fixo da SerpAPI.
                # Respostas iguais usam cache; só reservamos cota antes de uma chamada real.
                cache_params = {name: value for name, value in params.items() if name != 'api_key'}
                data = usage.cached('serp:' + key, cache_params) if usage else None
                if data is None:
                    http.checkpoint()
                    if filters.get('_cache_only'):
                        filters['_budget_limited'] = True
                        return jobs, notes + ['Consulta fora do cache; nenhuma nova chamada foi feita enquanto a fonte está sem saldo.']
                    try:
                        if budget:
                            budget.reserve()
                    except BudgetExceeded as exc:
                        filters['_budget_limited'] = True
                        return jobs, notes + [str(exc)]
                    try:
                        response = http.get("https://serpapi.com/search.json", params=params, timeout=25)
                        if response.status_code == 429 and budget:
                            budget.pause()
                        response.raise_for_status()
                        data = response.json()
                    except (requests.RequestException, ValueError):
                        return jobs, notes + ['Google Empregos indisponível. Confira a chave, a cota e tente mais tarde; as vagas de outras fontes foram preservadas.']
                    # Ausência de vagas não significa chave inválida nem cota esgotada.
                    error = str(data.get('error', '')).lower()
                    if error and any(text in error for text in ('no results', "hasn't returned any results", 'has not returned any results')):
                        data = {'jobs_results': []}
                        notes.append('Google Empregos não encontrou anúncios para um dos termos e locais consultados.')
                    if usage and not data.get('error'):
                        usage.remember('serp:' + key, cache_params, data)
                if data.get("error"):
                    if budget:
                        budget.pause()
                    return jobs, notes + ["A SerpAPI não retornou resultados. Confira a chave e a cota da sua conta."]
                for item in data.get("jobs_results", []):
                    options = item.get("apply_options", [])
                    link = next((option.get("link") for option in options if safe_link(option.get("link"))), "")
                    link = link or safe_link(item.get("share_link")) or google_url({**filters, "keywords": [item.get("title", keyword)]})
                    extensions = item.get("detected_extensions", {})
                    job = make_job(item.get("title"), item.get("company_name"), item.get("location", ""), link, "Google Empregos",
                                   description=item.get("description", ""), remote=bool(extensions.get("work_from_home")),
                                   employment=extensions.get("schedule_type", ""), salary=extensions.get("salary", ""),
                                   posted_label=extensions.get("posted_at", ""))
                    if not job["country"]:
                        job.update(country=code, country_name=BY_CODE[code]["name"], country_basis="consulta")
                    jobs.append(job)
                next_token = data.get("serpapi_pagination", {}).get("next_page_token", "")
                if not next_token:
                    break
    return jobs, notes + ["Google Empregos via SerpAPI: busca localizada em " + ", ".join(BY_CODE[code]["name"] for code in codes[:2]) + "; país inferido da consulta quando ausente."]


COMPANY_PROVIDERS = {"smartrecruiters": smartrecruiters, "greenhouse": greenhouse, "greenhouse_eu": greenhouse,
                     "lever": lever, "lever_eu": lever, 'ashby': ashby, "website": website}


def enrich_company_jobs(company, jobs, filters):
    """Detalhes públicos complementam listagens resumidas; falha não apaga a vaga."""
    if company["provider"] != "smartrecruiters":
        return jobs, []
    seen, checked, failures = set(), 0, 0
    enriched = {}
    for job in jobs:
        if job["id"] in enriched:
            job.update(enriched[job["id"]])
            continue
        if job["id"] in seen or not job.get("detail_url"):
            continue
        seen.add(job["id"])
        if (checked >= 30 or not location_matches(job, filters)
                or not matching.assess(job, filters.get("profile", "both"), filters["keywords"], filters["strict_title"], filters["excluded"])["matched"]):
            continue
        checked += 1
        try:
            data = public_json(job["detail_url"])
            if data.get("active") is False:
                job["inactive"] = True
            sections = data.get("jobAd", {}).get("sections", {})
            ordered = [sections.get(key, {}) for key in ("jobDescription", "qualifications", "additionalInformation", "companyDescription")]
            ordered += [section for key, section in sections.items() if key not in {"jobDescription", "qualifications", "additionalInformation", "companyDescription"}]
            description = clean_text(" ".join(str(section.get("text", "")) for section in ordered if isinstance(section, dict)))[:12000]
            job["description"] = description
            pay = salary.provider_salary(data.get("compensation"))
            job["salary_data"] = pay
            job["salary"] = salary.salary_label(pay) or salary.published_salary_text(description) or job.get("salary", "")
            if safe_link(data.get("applyUrl")):
                job["link"] = data["applyUrl"]
            enriched[job["id"]] = {key: job[key] for key in ("description", "salary_data", "salary", "link")}
            if job.get("inactive"):
                enriched[job["id"]]["inactive"] = True
        except (requests.RequestException, ValueError, OSError, KeyError, TypeError):
            failures += 1
    notes = [f"Descrição e remuneração verificadas em {checked} detalhes públicos (limite de 30 por empresa); anúncios sem período de salário continuam para análise."]
    if failures:
        notes.append(f"{failures} detalhes não puderam ser lidos; vagas resumidas foram preservadas.")
    return jobs, notes


def run_search(filters, companies, usage=None, user_id=0):
    from . import gemini
    if filters.get('free_exploration'):
        # Preferência explícita prevalece sobre fallback e avaliação por IA.
        filters = {**filters, 'sources': ['companies'], 'auto_sources': False, '_skip_ai_ranking': True}
    with gemini.usage_scope(usage, user_id):
        if usage and filters.get('auto_sources') and os.getenv('AUTO_SOURCE_ROUTING', 'true').lower() == 'true':
            from .automatic import search
            return search(filters, companies, usage, user_id, _run_search)
        return _run_search(filters, companies, usage, user_id)


def _run_search(filters, companies, usage=None, user_id=0):
    providers = []
    skipped_companies = 0
    if "companies" in filters["sources"]:
        by_id = {company['id']: company for company in companies if company['enabled']}
        selected_companies = [by_id[identifier] for identifier in dict.fromkeys(filters['company_ids']) if identifier in by_id]
        skipped_companies = max(0, len(selected_companies) - company_search_limit())
        providers.extend((company["name"], COMPANY_PROVIDERS[company["provider"]], company)
                         for company in selected_companies[:company_search_limit()])
    if "google" in filters["sources"]:
        providers.append(("Google Empregos", google_jobs, None))
    if "jooble" in filters["sources"]:
        providers.append(("Jooble", jooble, None))
    if "gemini" in filters["sources"]:
        from . import gemini
        providers.append(("Gemini / Google Search", gemini.search_jobs, None))
    jobs, report = {}, []
    signatures = {}
    references, search_queries, search_suggestions = [], [], ""
    profile = filters.get("profile", "both")
    query_plan = matching.expand_queries(filters["keywords"], profile, filters.get("country", ""), filters.get("multilingual", True))
    for name, fetch, company in providers:
        try:
            http.checkpoint()
            limit = 24 if company else 3 if name == "Google Empregos" else 6
            source_filters = {**filters, "keywords": query_plan[:limit]}
            if name == "Jooble" and not filters.get("country"):
                # O vocabulário acompanha o país da chave, inclusive na busca global.
                available = [code for code in market_codes(filters) if code in jooble_keys()]
                if len(available) == 1:
                    source_filters["keywords"] = matching.expand_queries(filters["keywords"], profile, available[0], filters.get("multilingual", True), limit=6)
            if name == "Gemini / Google Search":
                found, notes, references, search_queries, search_suggestions = fetch(filters)
            elif name == 'Jooble':
                found, notes = fetch(source_filters, usage=usage, user_id=user_id) if usage else fetch(source_filters)
            elif name == 'Google Empregos':
                found, notes = fetch(source_filters, usage=usage, user_id=user_id) if usage else fetch(source_filters)
            else:
                found, notes = fetch_company_jobs(company, source_filters, usage) if company else fetch(source_filters)
            accepted, review_count, below_count = 0, 0, 0
            source_seen = set()
            for job in found:
                http.checkpoint()
                if job["id"] in source_seen:
                    continue
                source_seen.add(job["id"])
                if job.get("inactive") or not job["title"] or not job["link"] or not location_matches(job, filters):
                    continue
                assessment = matching.assess(job, profile, filters["keywords"], filters["strict_title"], filters["excluded"])
                if not assessment["matched"]:
                    continue
                job["match"] = assessment
                job["salary_check"] = salary.evaluate(job, filters.get("salary_min", 7000))
                status = job["salary_check"]["status"]
                if status == "below":
                    below_count += 1
                    continue
                if status == "review":
                    review_count += 1
                else:
                    accepted += 1
                signature = (matching.normalize(job["title"]), matching.normalize(job["company"]), matching.normalize(job["location"]))
                existing = signatures.get(signature)
                if existing and jobs[existing]["source"] != job["source"]:
                    if job["source"] not in jobs[existing]["sources"]:
                        jobs[existing]["sources"].append(job["source"])
                    if job["salary_check"]["status"] == "eligible" and jobs[existing]["salary_check"]["status"] == "review":
                        job["sources"] = jobs[existing]["sources"]
                        jobs[existing] = job
                else:
                    signatures[signature] = job["id"]
                    jobs[job["id"]] = job
            report.append({"name": name, "status": "limited" if source_filters.get('_budget_limited') and not found else "ok", "received": len(found), "matched": accepted,
                           "budget_limited": bool(source_filters.get('_budget_limited')),
                           "review": review_count, "below_minimum": below_count, "notes": notes,
                           "queries": source_filters["keywords"] if name != "Gemini / Google Search" else search_queries})
        except http.SearchDeadlineExceeded as exc:
            report.append({'name': name, 'status': 'limited', 'received': 0, 'matched': 0,
                           'time_limited': True, 'notes': [str(exc)]})
            break
        except NeedsConfiguration as exc:
            report.append({"name": name, "status": "pending", "received": 0, "matched": 0, "notes": [str(exc)]})
        except (requests.RequestException, ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            from .usage import BudgetExceeded
            if isinstance(exc, BudgetExceeded):
                report.append({'name': name, 'status': 'limited', 'received': 0, 'matched': 0, 'budget_limited': True, 'notes': [str(exc)]})
                continue
            missing = "SERPAPI_API_KEY" if name == "Google Empregos" else "JOOBLE_API_KEY" if name == "Jooble" else "GEMINI_API_KEY" if name == "Gemini / Google Search" else ""
            configured = ('present' if jooble_keys() else '') if name == 'Jooble' else os.getenv(missing, "").strip() if missing else "present"
            note = f"Configure {missing} em Integrações para ativar esta fonte." if not configured or configured.startswith("COLE_") else f"Falha nesta fonte ({type(exc).__name__}). As demais fontes foram mantidas."
            if name == "Gemini / Google Search":
                from .gemini import GeminiError
                if isinstance(exc, GeminiError):
                    note = str(exc)
            report.append({"name": name, "status": "pending" if not configured or configured.startswith("COLE_") else "error",
                           "received": 0, "matched": 0, "notes": [note]})
    candidates = list(jobs.values())
    if skipped_companies:
        report.append({'name': 'Empresas selecionadas', 'status': 'limited', 'received': 0, 'matched': 0,
                       'notes': [f'{skipped_companies} empresas selecionadas não foram consultadas. O limite desta execução é {company_search_limit()}; selecione outras empresas para continuar.']})
    if not filters.get('_skip_ai_ranking') and "gemini" in filters["sources"] and candidates and os.getenv('GEMINI_ENABLED', 'true').lower() == 'true' and os.getenv("GEMINI_API_KEY", "").strip() and not os.getenv("GEMINI_API_KEY", "").startswith("COLE_"):
        try:
            from . import gemini
            gemini.rank_jobs(candidates, profile, filters)
            report.append({"name": "Avaliação Gemini", "status": "ok", "received": min(len(candidates), 80), "matched": 0,
                           "notes": ["IA ordena até 80 vagas. O filtro de área e o salário mínimo continuam obrigatórios."]})
        except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError):
            report.append({"name": "Avaliação Gemini", "status": "error", "received": 0, "matched": 0,
                           "notes": ["Avaliação indisponível; classificação por especialidade mantida."]})
    candidates.sort(key=lambda job: (job.get("ai_assessment", {}).get("score", job["match"].get("score", 0)), job.get("updated") or ""), reverse=True)
    return {"jobs": [job for job in candidates if job["salary_check"]["status"] == "eligible"][:500],
            "review_jobs": [job for job in candidates if job["salary_check"]["status"] == "review"][:500],
            "research_sources": references, "query_plan": query_plan, "search_suggestions": search_suggestions,
            "reports": report, "budget_limited": any(item.get('budget_limited') for item in report),
            "time_limited": any(item.get('time_limited') for item in report), "google_url": google_url(filters),
            "coverage": "Resultados das fontes e páginas consultadas; nenhuma busca garante todas as vagas do mundo."}
