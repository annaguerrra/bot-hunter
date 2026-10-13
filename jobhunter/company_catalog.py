"""Páginas públicas verificadas em 12/10/2026; cada usuário mantém seu radar."""

DEFAULT_COMPANIES = [
    {"name": "Bosch", "url": "https://careers.bosch.com/", "provider": "smartrecruiters", "identifier": "BoschGroup"},
    {"name": "Continental / ContiTech", "url": "https://careers.smartrecruiters.com/ContinentalGroupSectorContiTech", "provider": "smartrecruiters", "identifier": "ContinentalGroupSectorContiTech"},
    {"name": "BEUMER Group", "url": "https://careers.smartrecruiters.com/BEUMERGroup1", "provider": "smartrecruiters", "identifier": "BEUMERGroup1"},
    {"name": "Renesas Electronics", "url": "https://careers.smartrecruiters.com/RenesasElectronics", "provider": "smartrecruiters", "identifier": "RenesasElectronics"},
    {"name": "Sika", "url": "https://careers.smartrecruiters.com/SikaAG", "provider": "smartrecruiters", "identifier": "SikaAG"},
]

# O catálogo é público e separado do radar privado. Novos itens nunca refazem o seed.
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from .matching import normalize
from .geo import BY_CODE

AREAS = ['engenharia de produção', 'engenharia de produto', 'manufatura', 'qualidade',
         'supply chain', 'operações', 'automação', 'gestão de projetos']
CATALOG_PROVIDERS = {'smartrecruiters', 'greenhouse', 'lever', 'ashby'}
PROVIDER_HOSTS = {'smartrecruiters': 'careers.smartrecruiters.com', 'greenhouse': 'job-boards.greenhouse.io',
                  'lever': 'jobs.lever.co', 'ashby': 'jobs.ashbyhq.com'}


def identity(company):
    return company['provider'].lower(), (company.get('identifier') or company['url']).lower().rstrip('/')


def validate_catalog(data):
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('companies'), list) or not isinstance(data.get('manual_only', []), list):
        raise ValueError('Versão do catálogo inválida.')
    seen = set()
    for item in data['companies']:
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str) for key in ('name', 'url', 'provider', 'identifier', 'status')):
            raise ValueError('Registro incompleto no catálogo.')
        parts = urlsplit(item['url'])
        if (item['provider'] not in CATALOG_PROVIDERS or not re.fullmatch(r'[A-Za-z0-9._-]{1,120}', item['identifier'])
                or parts.scheme != 'https' or parts.username or parts.password
                or parts.hostname != PROVIDER_HOSTS.get(item['provider'])
                or parts.path.strip('/') != item['identifier'] or parts.query or parts.port not in (None, 443)
                or not isinstance(item['name'], str) or not 1 <= len(item['name']) <= 80
                or item['status'] not in {'validated', 'api_pending'} or item.get('default_enabled') is not False
                or not isinstance(item['tags'], list) or not all(isinstance(tag, str) for tag in item['tags'])
                or not isinstance(item.get('geography'), list) or not all(isinstance(code, str) and (code == 'global' or code in BY_CODE) for code in item['geography'])):
            raise ValueError('Registro inválido no catálogo de empresas.')
        key = identity(item)
        if key in seen:
            raise ValueError('Empresa duplicada no catálogo.')
        seen.add(key)
    for item in data.get('manual_only', []):
        if not isinstance(item, dict) or not isinstance(item.get('url'), str) or not isinstance(item.get('name'), str):
            raise ValueError('Página externa incompleta.')
        parts = urlsplit(item['url'])
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
            raise ValueError('Página externa inválida.')
    return data


@lru_cache(maxsize=1)
def suggestions():
    data = validate_catalog(json.loads((Path(__file__).resolve().parents[1] / 'resources/companies.json').read_text(encoding='utf-8')))
    defaults = [{**item, 'tags': ['engenharia de produto', 'manufatura', 'engenharia de produção'],
                 'geography': ['global'], 'status': 'validated', 'validated_at': '2026-10-12'} for item in DEFAULT_COMPANIES]
    manual = [{**item, 'provider': 'website', 'identifier': '', 'tags': ['manufatura', 'automação'],
               'geography': ['US'], 'status': 'manual_only'} for item in data.get('manual_only', [])]
    return [{**item, 'catalog_id': ':'.join(identity(item))} for item in defaults + data['companies'] + manual]


def ranked(filters):
    country, region = filters.get('country', ''), filters.get('region', '')
    wanted = filters.get('keywords', []) if filters.get('profile') == 'custom' else ['engenharia de produto', 'hardware', 'automação'] if filters.get('profile') == 'product' else ['produção', 'manufatura', 'qualidade', 'operações', 'processos']
    def score(item):
        tags = normalize(' '.join(item['tags']))
        return (country in item['geography'], sum(normalize(term) in tags for term in wanted), normalize(item['name']))
    items = [item for item in suggestions() if (not country or 'global' in item['geography'] or country in item['geography'])
             and (not region or 'global' in item['geography'] or any(BY_CODE.get(code, {}).get('region') == region for code in item['geography']))]
    return sorted(items, key=score, reverse=True)


def catalog_page(registered, *, q='', provider='', area='', country='', region='', geography='', profile='both', offset=0):
    known = {identity(item): item for item in registered}
    items = []
    for item in ranked({'country': country, 'region': region, 'profile': profile}):
        if q and normalize(q) not in normalize(item['name'] + ' ' + ' '.join(item['tags'])):
            continue
        if provider and item['provider'] != provider:
            continue
        if area and normalize(area) not in normalize(' '.join(item['tags'])):
            continue
        if geography == 'international' and not ('global' in item['geography'] or any(code != 'BR' for code in item['geography'])):
            continue
        own = known.get(identity(item))
        items.append({**item, 'registered_id': own['id'] if own else None, 'enabled': bool(own and own['enabled']),
                      'registration': 'active' if own and own['enabled'] else 'paused' if own else 'available',
                      'compatible_count': None})
    return {'companies': items[offset:offset + 10], 'total': len(items), 'offset': offset, 'limit': 10, 'areas': AREAS}
