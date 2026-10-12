"""Domínios publicados em https://jooble.org/ em 12/10/2026 (66 mercados)."""
from .geo import BY_CODE

CODES = "UA PL CZ RO SK RS HU GR FR FI NO ES PT CH SE DK BE DE AT NL IT GB IE TR BA HR BG KZ IN SG PH PK TH JP TW HK ID KR AZ MY AE SA QA KW BH UZ US MX AR CL CO PE DO CR UY SV PR BR CA EC NZ AU NG ZA EG MA".split()
HOSTS = {code: {"US": "jooble.org", "GB": "uk.jooble.org", "JP": "ja.jooble.org"}.get(code, code.lower() + ".jooble.org") for code in CODES}
MARKETS = sorted([{**BY_CODE[code], "host": host, "signup_url": "https://" + host + "/api/about"}
                  for code, host in HOSTS.items()], key=lambda item: item["name"])
