"""Vocabulário compartilhado pelo site e pelos alertas, sem depender de IA."""
import re
import unicodedata


def normalize(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).strip()


ALIASES = {
    "product": {
        "en": ["product engineer", "product development engineer", "mechanical design engineer", "research and development engineer"],
        "pt": ["engenheiro de produto", "engenheiro de desenvolvimento de produto", "engenheiro de projetos mecânicos", "engenheiro de P&D"],
        "es": ["ingeniero de producto", "ingeniero de desarrollo de producto"],
        "de": ["Produktentwickler", "Entwicklungsingenieur", "Konstruktionsingenieur"],
        "fr": ["ingénieur produit", "ingénieur développement produit"],
        "it": ["ingegnere di prodotto", "ingegnere progettista"],
        "ja": ["製品開発", "設計エンジニア"], "zh": ["产品工程师", "產品工程師", "产品开发工程师"],
        "ko": ["제품 개발 엔지니어"],
    },
    "production": {
        "en": ["production engineer", "manufacturing engineer", "industrial engineer", "process engineer"],
        "pt": ["engenheiro de produção", "engenheiro de manufatura", "engenheiro de processos", "coordenador de produção industrial"],
        "es": ["ingeniero de producción", "ingeniero industrial", "ingeniero de procesos"],
        "de": ["Produktionsingenieur", "Fertigungsingenieur", "Prozessingenieur"],
        "fr": ["ingénieur de production", "ingénieur procédés", "ingénieur industriel"],
        "it": ["ingegnere di produzione", "ingegnere industriale"],
        "ja": ["生産技術", "製造エンジニア"], "zh": ["生产工程师", "製造工程師", "制造工程师", "工业工程师"],
        "ko": ["생산 엔지니어", "제조 엔지니어"],
    },
}
LANGUAGES = {"BR": "pt", "PT": "pt", "DE": "de", "AT": "de", "CH": "de", "FR": "fr", "BE": "fr",
             "IT": "it", "ES": "es", "MX": "es", "AR": "es", "CL": "es", "CO": "es", "PE": "es",
             "JP": "ja", "CN": "zh", "TW": "zh", "KR": "ko"}
UNRELATED = ["comercial", "commercial", "sales", "vendas", "administrativo", "administrative", "cozinha", "kitchen",
             "recursos humanos", "human resources", "rh", "fiscal", "contabilidade", "accounting", "importacao",
             "importacion", "civil", "obras", "construction", "imobiliaria", "real estate", "empregabilidade",
             "eventos", "events", "event production", "software", "sw", "frontend", "backend", "full stack"]


def contains(text, term):
    text, term = normalize(text), normalize(term)
    if not term:
        return False
    if any("\u3400" <= char <= "\u9fff" or "\u3040" <= char <= "\u30ff" for char in term):
        return term in text
    return " " + term + " " in " " + text + " "


def areas(profile):
    return [profile] if profile in ALIASES else ["product", "production"] if profile == "both" else []


def title_form(value):
    value = normalize(value)
    # Singular/plural e gênero dos nomes de cargos; não amplia coordenador sozinho.
    value = re.sub(r"\bengenheir[oa]s?\b", "engenheiro", value)
    value = re.sub(r"\bingenier[oa]s?\b", "ingeniero", value)
    value = re.sub(r"\bengineers\b", "engineer", value)
    value = re.sub(r"\bcoordenador[ae]?s?\b", "coordenador", value)
    value = re.sub(r"\b(do|da|dos|das)\b", "de", value)
    return value


def assess(job, profile="both", keywords=(), strict=True, excluded=()):
    title = title_form(job.get("title"))
    description = normalize(job.get("description") or job.get("snippet", ""))
    if not title or any(contains(title, term) for term in excluded):
        return {"matched": False, "reason": "Título ausente ou termo excluído"}
    if profile == "custom":
        matched = not strict or any(contains(title, title_form(term)) for term in keywords)
        return {"matched": matched, "area": "custom", "score": 60, "reason": "Filtro de título personalizado"}
    if any(contains(title, term) for term in UNRELATED):
        return {"matched": False, "reason": "Cargo de outra área"}
    physical = any(contains(description, term) for term in ["manufacturing", "mechanical", "hardware", "automotive", "industrial", "factory", "fabrica", "manufatura", "mecanico", "CAD", "CAE", "prototipo", "produto fisico"])
    digital = any(contains(description, term) for term in ["SaaS", "web application", "web applications", "frontend", "backend", "full stack"])
    if digital and not physical:
        return {"matched": False, "reason": "Descrição indica produto de software"}
    for area in areas(profile):
        aliases = [alias for group in ALIASES[area].values() for alias in group]
        if any(contains(title, title_form(alias)) for alias in aliases):
            return {"matched": True, "area": area, "score": 90 if area == "product" else 85,
                    "reason": "Cargo de engenharia de produto" if area == "product" else "Cargo de engenharia de produção/manufatura"}
        domains = r"\b(produtos?|products?|productos?|produits?|prodott[oi]|mechanical design)\b" if area == "product" else r"\b(producao|production|produccion|manufacturing|manufatura|industrial|processos|process|processes|procedes)\b"
        roles = r"\b(engenheiro|ingeniero|engineer|ingenieur|ingegnere|eng|ing)\b"
        if re.search(roles, title) and re.search(domains, title):
            return {"matched": True, "area": area, "score": 80, "reason": "Cargo e especialidade compatíveis"}
        if area == "product" and re.search(r"\b(engenharia|engineering|desenvolvimento|development)\b", title) and re.search(domains, title) and physical:
            return {"matched": True, "area": area, "score": 75, "reason": "Desenvolvimento de produto físico confirmado na descrição"}
    return {"matched": False, "reason": "Título sem evidência da especialidade escolhida"}


def expand_queries(keywords, profile="both", country="", multilingual=True, limit=24):
    result = []
    local = LANGUAGES.get(country, "en")
    languages = list(dict.fromkeys([local, "en", "pt"] if country else ["en", "pt", "es", "de", "fr", "it", "zh", "ja", "ko"]))
    if multilingual and areas(profile):
        # Intercala produto/produção e idiomas antes de incluir sinônimos adicionais.
        for index in range(4):
            for lang in languages:
                for area in areas(profile):
                    terms = ALIASES[area].get(lang, [])
                    if index < len(terms):
                        result.append(terms[index])
    if multilingual and areas(profile):
        # Preserva os termos escritos pela pessoa, mas distribui primeiro as duas áreas.
        result = result[:min(2, len(result))] + list(keywords) + result[min(2, len(result)):]
    else:
        result = list(keywords)
    unique = {}
    for term in result:
        unique.setdefault(normalize(term), term)
    return list(unique.values())[:limit]
