"""Compara remuneração publicada; valores incertos nunca liberam alertas."""
import math
import re
import threading
import time
from datetime import date

import requests
import pycountry

from .matching import normalize

_cache = {}
_lock = threading.Lock()
_currencies = {item.alpha_3 for item in pycountry.currencies}


def exchange_rate(currency):
    if currency == "BRL":
        return 1.0, date.today().isoformat()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Moeda desconhecida")
    with _lock:
        cached = _cache.get(currency)
        if cached and time.monotonic() - cached[0] < 28800:
            return cached[1], cached[2]
        response = requests.get("https://api.frankfurter.dev/v2/rate/" + currency.lower() + "/brl", timeout=(5, 15))
        response.raise_for_status()
        data = response.json()
        rate, rate_date = float(data["rate"]), str(data["date"])
        age = (date.today() - date.fromisoformat(rate_date)).days
        if not math.isfinite(rate) or rate <= 0 or not -1 <= age <= 10:
            raise ValueError("Cotação inválida ou desatualizada")
        _cache[currency] = (time.monotonic(), rate, rate_date)
        return rate, rate_date


def number(value):
    value = str(value).strip().replace(" ", "").replace("'", "")
    if "," in value and "." in value:
        decimal = "," if value.rfind(",") > value.rfind(".") else "."
        value = value.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif re.fullmatch(r"\d{1,3}([.,]\d{3})+", value):
        value = value.replace(",", "").replace(".", "")
    else:
        value = value.replace(",", ".")
    return float(value)


def parse_salary(job):
    structured = job.get("salary_data") or {}
    if structured:
        amount = structured.get("min", structured.get("value"))
        if amount is None or isinstance(amount, bool):
            return None
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return None
        period = str(structured.get("period", "")).upper()
        period = {"YEARLY": "YEAR", "ANNUAL": "YEAR", "MONTHLY": "MONTH", "WEEKLY": "WEEK", "HOURLY": "HOUR"}.get(period, period)
        return {"amount": amount, "currency": str(structured.get("currency", "")).upper(),
                "period": period, "hours": structured.get("hours_per_week")}
    raw = str(job.get("salary") or "")
    text = normalize(raw)
    if not raw or re.search(r"\b(a combinar|negociavel|competitive|negotiable|estimated|estimado|estimate)\b", text):
        return None
    # Um teto não é um salário mínimo garantido.
    if re.search(r"\b(ate|up to|hasta|bis zu|jusqu a)\b", text):
        return None
    currencies = {code for code in re.findall(r"(?<![A-Z])([A-Z]{3})(?![A-Z])", raw.upper()) if code in _currencies}
    if "RMB" in raw.upper():
        currencies.add("CNY")
    for symbol, code in [("R$", "BRL"), ("US$", "USD"), ("€", "EUR"), ("£", "GBP"), ("₹", "INR")]:
        if symbol in raw:
            currencies.add(code)
    if "$" in raw and not currencies and job.get("country_basis") != "consulta":
        code = {"US": "USD", "CA": "CAD", "AU": "AUD", "NZ": "NZD", "SG": "SGD", "MX": "MXN"}.get(job.get("country"))
        if code:
            currencies.add(code)
    if len(currencies) != 1:
        return None
    found = re.findall(r"\d[\d.,'\u00a0 ]*\d|\d+(?:[.,]\d+)?", raw)
    values = []
    for token in found:
        try:
            amount = number(token)
            tail = raw[raw.find(token) + len(token):].lstrip()
            if re.match(r"(k\b|mil\b|thousand\b|万|萬)", tail, re.I):
                amount *= 1000
                if tail.startswith(("万", "萬")):
                    amount *= 10
            elif re.match(r"(lpa\b|lakhs?\b|lacs?\b)", tail, re.I):
                amount *= 100000
            values.append(amount)
        except ValueError:
            continue
    if not values or len(values) > 2:
        return None
    # '80–100k' usa o sufixo para ambos os lados do intervalo.
    if len(values) == 2 and values[0] < 1000 < values[1] and re.search(r"\d\s*k\b", raw, re.I):
        values[0] *= 1000
    period = ""
    for unit, pattern in [("YEAR", r"\b(year|yearly|annual|annually|ano|anual|annum|jahr|jahrlich|an|annuel|annuelle|annuo|lpa)\b|年薪|年収|/年"),
                          ("MONTH", r"\b(month|monthly|mes|mensal|mensual|mensuales|mensuel|mensuelle|mensile|mese|monat|mois)\b|月薪|/月"),
                          ("WEEK", r"\b(week|weekly|semana|semanal)\b"), ("HOUR", r"\b(hour|hourly|hora|stunde)\b")]:
        if re.search(pattern, text):
            period = unit
            break
    return {"amount": min(values), "currency": next(iter(currencies)), "period": period, "hours": job.get("hours_per_week")}


def evaluate(job, minimum=7000, rate_fetch=exchange_rate):
    result = {"status": "review", "minimum_brl": minimum, "reason": "Salário não informado ou sem moeda/período verificável"}
    parsed = parse_salary(job)
    if not parsed:
        return result
    amount, period, currency = parsed["amount"], parsed["period"], parsed["currency"]
    if not math.isfinite(amount) or amount <= 0 or not re.fullmatch(r"[A-Z]{3}", currency):
        return result
    if period == "YEAR":
        monthly = amount / 12
    elif period == "MONTH":
        monthly = amount
    elif period == "WEEK":
        monthly = amount * 52 / 12
    elif period == "HOUR":
        try:
            hours = float(parsed["hours"])
        except (TypeError, ValueError):
            return {**result, "reason": "Salário por hora sem jornada semanal informada"}
        if not math.isfinite(hours) or not 0 < hours <= 80:
            return result
        monthly = amount * hours * 52 / 12
    else:
        return result
    try:
        rate, rate_date = rate_fetch(currency)
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return {**result, "reason": "Conversão pendente: cotação indisponível ou desatualizada", "currency": currency}
    brl = monthly * rate
    status = "eligible" if brl >= minimum else "below"
    return {"status": status, "minimum_brl": minimum, "monthly_brl": round(brl, 2), "monthly_original": round(monthly, 2),
            "currency": currency, "rate": rate, "rate_date": rate_date, "original_period": period,
            "rate_source": "Frankfurter" if currency != "BRL" else "BRL",
            "reason": "Piso publicado atende ao mínimo" if status == "eligible" else "Piso publicado abaixo do mínimo"}


def schema_salary(item):
    salary = item.get("baseSalary") or {}
    if not isinstance(salary, dict):
        return {}
    value = salary.get("value") or {}
    if not isinstance(value, dict):
        return {}
    return {"currency": salary.get("currency", ""), "min": value.get("minValue", value.get("value")),
            "max": value.get("maxValue"), "period": value.get("unitText", "")}


def published_salary_text(description):
    """Extrai apenas uma frase com remuneração e moeda; não lê números de requisitos."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n", description):
        if (re.search(r"salary|base pay|sal[aá]rio|remunera|sueldo|gehalt|compensation|salaire", sentence, re.I)
                and re.search(r"[$€£₹]\s*\d|\b(?:BRL|USD|EUR|GBP|CAD|AUD|INR)\s*\d", sentence, re.I)):
            return sentence[:1200]
    return ""


def provider_salary(value):
    if not isinstance(value, dict) or value.get("min") is None:
        return {}
    return {"min": value["min"], "max": value.get("max"), "currency": value.get("currency", ""),
            "period": value.get("period") or value.get("interval", "")}


def salary_label(data):
    if not data:
        return ""
    period = {"YEARLY": "ano", "YEAR": "ano", "MONTHLY": "mês", "MONTH": "mês", "HOURLY": "hora", "HOUR": "hora"}.get(str(data.get("period", "")).upper(), "período não informado")
    return str(data.get("currency", "")) + " " + str(data.get("min", "")) + (" – " + str(data["max"]) if data.get("max") is not None else "") + " / " + period
