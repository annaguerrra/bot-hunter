"""Verificação opcional de APIs públicas, sem chaves ou cadastro de empresas."""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobhunter import providers


def endpoint(company):
    identifier = company['identifier']
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,120}', identifier):
        raise ValueError('Identificador inválido.')
    slug = quote(identifier, safe='')
    return {
        'smartrecruiters': f'https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1&destination=PUBLIC',
        'greenhouse': f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs',
        'lever': f'https://api.lever.co/v0/postings/{slug}?mode=json&limit=1',
        'ashby': f'https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true',
    }[company['provider']]


def check(company):
    result = {'company': company['name'], 'provider': company['provider'], 'identifier': company['identifier']}
    try:
        data = providers.public_json(endpoint(company))
        items = data if company['provider'] == 'lever' else data.get('content' if company['provider'] == 'smartrecruiters' else 'jobs')
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError('Formato inesperado.')
        result.update(status='validated', returned=len(items), total=data.get('totalFound') if isinstance(data, dict) else None)
        result['sample'] = [{key: item.get(key) for key in ('title', 'name', 'text', 'jobUrl', 'absolute_url', 'hostedUrl')} for item in items[:2]]
    except (ValueError, OSError, KeyError, TypeError, providers.requests.RequestException) as exc:
        result.update(status='api_pending', reason=type(exc).__name__)
        if getattr(exc, 'response', None) is not None:
            result['http_status'] = exc.response.status_code
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', default='resources/companies.json')
    parser.add_argument('--limit', type=int, choices=range(1, 21), default=15)
    args = parser.parse_args()
    catalog = json.loads(Path(args.catalog).read_text(encoding='utf-8-sig'))
    for company in catalog['companies'][:args.limit]:
        print(json.dumps(check(company), ensure_ascii=True), flush=True)
