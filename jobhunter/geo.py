"""Países ISO 3166, subdivisões e continentes, sem chamadas externas em runtime."""
import gettext
import json
from pathlib import Path

import pycountry

from main import normalize

REGIONS = {"AF": "África", "AM": "Américas", "AS": "Ásia", "EU": "Europa", "OC": "Oceania", "AN": "Antártida"}
CONTINENTS = json.loads((Path(__file__).parent / "continents.json").read_text(encoding="utf-8"))
TRANSLATE = gettext.translation("iso3166-1", pycountry.LOCALES_DIR, languages=["pt"], fallback=True).gettext
COUNTRIES = sorted([
    {"code": item.alpha_2, "name": TRANSLATE(item.name), "english": item.name,
     "region": CONTINENTS.get(item.alpha_2, "AN")}
    for item in pycountry.countries
], key=lambda item: normalize(item["name"]))
BY_CODE = {item["code"]: item for item in COUNTRIES}


def country_code(value):
    if isinstance(value, dict):
        value = value.get("name", "")
    if not isinstance(value, str) or not value.strip():
        return ""
    value = value.strip()
    if value.upper() in BY_CODE:
        return value.upper()
    aliases = {"uk": "GB", "usa": "US", "brasil": "BR", "deutschland": "DE", "south korea": "KR"}
    if normalize(value) in aliases:
        return aliases[normalize(value)]
    for item in COUNTRIES:
        if normalize(value) in {normalize(item["name"]), normalize(item["english"])}:
            return item["code"]
    try:
        return pycountry.countries.lookup(value).alpha_2
    except LookupError:
        return ""


def states(code):
    return sorted([{"code": item.code, "name": item.name, "type": item.type}
                   for item in pycountry.subdivisions.get(country_code=code) or []], key=lambda item: item["name"])


def state_names(code):
    item = pycountry.subdivisions.get(code=code) if code else None
    return [item.name, item.code.split("-", 1)[-1]] if item else []


def location_matches(job, filters):
    country = job.get("country", "")
    if filters.get("country") and country != filters["country"]:
        return False
    if filters.get("region") and (not country or BY_CODE.get(country, {}).get("region") != filters["region"]):
        return False
    text = " " + normalize(job.get("location", "") + " " + job.get("state", "")) + " "
    names = state_names(filters.get("state", ""))
    if names and not any(" " + normalize(name) + " " in text for name in names):
        return False
    if filters.get("city") and normalize(filters["city"]) not in text:
        return False
    if filters.get("remote") and not job.get("remote"):
        return False
    return True
