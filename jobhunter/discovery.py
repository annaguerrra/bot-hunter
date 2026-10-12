"""Sugestões de empresas: fontes citadas e vagas verificadas antes do cadastro."""
import json
import os

import requests

from . import gemini, matching, providers
from .company_catalog import DEFAULT_COMPANIES
from .geo import location_matches


def suggest_companies(filters, registered):
    candidates, notes, grounding = [], [], {}
    if os.getenv('GEMINI_API_KEY', '').strip() and os.getenv('GEMINI_ENABLED', 'true').lower() == 'true':
        try:
            data, grounding = gemini.generate(
                'Pesquise com Google Search empresas com anúncios atuais para este perfil e localização. '
                'Encontre páginas oficiais de carreiras ou seus portais oficiais SmartRecruiters, Greenhouse ou Lever. '
                'Não indique agregadores, cursos ou agências sem vagas verificáveis. Não invente sites nem salários. '
                'Cada URL deve aparecer nas fontes citadas. Retorne até cinco empresas em JSON '
                '{"companies":[{"name":"Empresa","url":"https://...","reason":"relação com o perfil"}]}. Critérios: '
                + json.dumps({'profile': filters['profile'], 'keywords': filters['keywords'],
                              'country': filters['country'], 'region': filters['region'], 'city': filters['city']}, ensure_ascii=False), search=True)
            cited = {providers.safe_link(chunk.get('web', {}).get('uri')) for chunk in grounding.get('groundingChunks', [])}
            entries = data.get('companies', [])
            if isinstance(entries, list):
                for item in entries[:5]:
                    if isinstance(item, dict) and item.get('url') in cited and isinstance(item.get('name'), str):
                        candidates.append({'name': item['name'][:80], 'url': item['url'], 'origin': 'Gemini / Google Search'})
            notes.append('Sugestões Gemini só entram no radar depois da verificação de anúncios públicos compatíveis.')
        except gemini.GeminiError as exc:
            notes.append(str(exc))
        except (requests.RequestException, ValueError, OSError):
            notes.append('A pesquisa Gemini está indisponível. O catálogo público será verificado.')
    else:
        notes.append('Configure Gemini para descobrir novas empresas com pesquisa Google.')
    candidates.extend({**item, 'origin': 'Catálogo público verificado'} for item in DEFAULT_COMPANIES)
    known = {(item['provider'], item['identifier']): item for item in registered}
    query = {**filters, 'keywords': matching.expand_queries(filters['keywords'], filters['profile'], filters['country'], filters['multilingual'], limit=2), 'pages': 1}
    if filters['profile'] != 'custom':
        query['keywords'] = list(dict.fromkeys(query['keywords'] + ['engineer']))
    suggestions, checked = [], set()
    for candidate in candidates[:10]:
        try:
            company = providers.discover_company(candidate['name'], candidate['url'])
            identity = (company['provider'], company['identifier'] or company['url'])
            if identity in checked:
                continue
            checked.add(identity)
            adapter = providers.COMPANY_PROVIDERS.get(company['provider'])
            if not adapter:
                continue
            jobs, _ = adapter(company, query)
            compatible = [job for job in jobs if matching.assess(job, filters['profile'], filters['keywords'], filters['strict_title'], filters['excluded'])['matched'] and location_matches(job, filters)]
            if not compatible:
                continue
            suggestions.append({**company, 'origin': candidate['origin'], 'registered_id': known.get(identity, {}).get('id'),
                                'enabled': known.get(identity, {}).get('enabled', False),
                                'evidence': [{'title': job['title'], 'location': job['location'], 'url': job['link']} for job in compatible[:3]],
                                'note': 'Vagas compatíveis verificadas; remuneração será conferida na busca. Salário mínimo não é garantido pela empresa.'})
            if len(suggestions) >= 5:
                break
        except (requests.RequestException, ValueError, OSError, KeyError, TypeError):
            continue
    references = [{'url': providers.safe_link(chunk.get('web', {}).get('uri')), 'title': str(chunk.get('web', {}).get('title', 'Fonte'))[:180]} for chunk in grounding.get('groundingChunks', [])]
    return {'kind': 'company_discovery', 'companies': suggestions, 'notes': notes,
            'research_sources': [item for item in references if item['url']][:20],
            'search_suggestions': str(grounding.get('searchEntryPoint', {}).get('renderedContent', ''))[:100000]}
