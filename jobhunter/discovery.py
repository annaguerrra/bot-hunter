"""Sugestões de empresas: fontes citadas e vagas verificadas antes do cadastro."""
import json
import os

import requests

from . import gemini, matching, providers, http
from .company_catalog import ranked
from .geo import location_matches


def suggest_companies(filters, registered, *, offset=0, usage=None, use_gemini=False):
    candidates, notes, grounding = [], [], {}
    if use_gemini and os.getenv('GEMINI_API_KEY', '').strip() and os.getenv('GEMINI_ENABLED', 'true').lower() == 'true':
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
        except http.SearchDeadlineExceeded as exc:
            notes.append(str(exc))
        except gemini.GeminiError as exc:
            notes.append(str(exc))
        except (requests.RequestException, ValueError, OSError):
            notes.append('A pesquisa Gemini está indisponível. O catálogo público será verificado.')
    elif use_gemini:
        notes.append('Configure Gemini para descobrir novas empresas com pesquisa Google.')
    else:
        notes.append('Descoberta direta em portais públicos, sem Jooble, SerpAPI ou Gemini. Cadastro não inicia consultas.')
    candidates.extend({**item, 'origin': 'Catálogo público verificado'} for item in ranked(filters) if item['status'] == 'validated')
    known = {(item['provider'], item['identifier']): item for item in registered}
    query = {**filters, 'keywords': matching.expand_queries(filters['keywords'], filters['profile'], filters['country'], filters['multilingual'], limit=2), 'pages': 1}
    if filters['profile'] != 'custom':
        query['keywords'] = list(dict.fromkeys(query['keywords'] + ['engineer']))
    suggestions, checked, reports = [], set(), []
    checked_candidates = candidates[offset:offset + 5]
    for candidate in checked_candidates:
        try:
            http.checkpoint()
            company = providers.discover_company(candidate['name'], candidate['url'])
            identity = (company['provider'], company['identifier'] or company['url'])
            if identity in checked:
                continue
            checked.add(identity)
            adapter = providers.COMPANY_PROVIDERS.get(company['provider'])
            if not adapter:
                continue
            jobs, cache_notes = providers.fetch_company_jobs(company, query, usage)
            notes.extend(cache_notes)
            compatible = [job for job in jobs if matching.assess(job, filters['profile'], filters['keywords'], filters['strict_title'], filters['excluded'])['matched'] and location_matches(job, filters)]
            reports.append({'name': company['name'], 'status': 'ok', 'received': len(jobs), 'compatible': len(compatible),
                            'cache': any('cache' in note for note in cache_notes)})
            if not compatible:
                continue
            suggestions.append({**company, 'origin': candidate['origin'], 'compatible_count': len(compatible), 'registered_id': known.get(identity, {}).get('id'),
                                'enabled': known.get(identity, {}).get('enabled', False),
                                'evidence': [{'title': job['title'], 'location': job['location'], 'url': job['link']} for job in compatible[:3]],
                                'note': 'Vagas compatíveis verificadas; remuneração será conferida na busca. Salário mínimo não é garantido pela empresa.'})
            if len(suggestions) >= 5:
                break
        except http.SearchDeadlineExceeded as exc:
            notes.append(str(exc))
            break
        except (requests.RequestException, ValueError, RuntimeError, OSError, KeyError, TypeError):
            reports.append({'name': candidate['name'], 'status': 'unavailable', 'received': None, 'compatible': None, 'cache': False})
            notes.append(candidate['name'] + ': portal indisponível nesta verificação; as outras empresas foram mantidas.')
            continue
    references = [{'url': providers.safe_link(chunk.get('web', {}).get('uri')), 'title': str(chunk.get('web', {}).get('title', 'Fonte'))[:180]} for chunk in grounding.get('groundingChunks', [])]
    return {'kind': 'company_discovery', 'companies': suggestions, 'notes': notes,
            'reports': reports,
            'checked_count': len(checked_candidates), 'total_candidates': len(candidates),
            'next_offset': offset + 5 if offset + 5 < len(candidates) else None,
            'research_sources': [item for item in references if item['url']][:20],
            'search_suggestions': str(grounding.get('searchEntryPoint', {}).get('renderedContent', ''))[:100000]}
