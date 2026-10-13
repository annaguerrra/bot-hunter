"""Seleção automática de fontes e atividades, respeitando local, cotas e conta."""
import json
import os
from datetime import datetime
from . import gemini, matching, http
from .database import connection
from .gemini_usage import GeminiBudget
from .google_usage import GoogleBudget
from .guidance import guidance
from .geo import location_matches

def resources(filters, companies, usage, user_id):
    from .providers import jooble_keys, market_codes
    keys = {code: key for code, key in jooble_keys().items() if code in market_codes(filters)}
    jooble = usage.snapshot(user_id, keys, admin=True)
    markets = jooble.pop('markets')
    # O teto total estimado da chave não renova à meia-noite.
    if not any(market['remaining_estimate'] for market in markets):
        jooble['resets_at'] = None
    google = GoogleBudget(usage).snapshot()
    ai = GeminiBudget(usage, user_id).snapshot()
    return {'jooble': {**jooble, 'configured': bool(keys)},
            'google': {**google, 'configured': bool(os.getenv('SERPAPI_API_KEY', '').strip()),
                       'blocked': not google['remaining_today'] or google['blocked_until'] > usage.clock()},
            'gemini': {**ai, 'configured': bool(os.getenv('GEMINI_API_KEY', '').strip())},
            'companies': {'configured': any(company['enabled'] and company['id'] in filters['company_ids'] for company in companies)}}


def saved_opportunities(filters, usage, user_id):
    # Apenas dados desta pessoa; oportunidades antigas nunca entram nos novos alertas.
    with connection(usage.path, usage.database_url) as db:
        favorites = db.execute('SELECT payload FROM favorites WHERE user_id=?', (user_id,)).fetchall()
        history = db.execute("SELECT result FROM searches WHERE user_id=? AND status='done' ORDER BY created_at DESC LIMIT 5", (user_id,)).fetchall()
    candidates = [json.loads(row['payload']) for row in favorites]
    for row in history:
        result = json.loads(row['result'])
        candidates.extend(result.get('jobs', []) + result.get('review_jobs', []))
    found = {}
    for job in candidates:
        if not job.get('id') or not job.get('title') or not job.get('link') or job.get('inactive'):
            continue
        if location_matches(job, filters) and matching.assess(job, filters['profile'], filters['keywords'], filters['strict_title'], filters['excluded'])['matched']:
            found[job['id']] = {key: job.get(key, '') for key in ('id', 'title', 'company', 'location', 'link')}
        if len(found) >= 20:
            break
    return list(found.values())


def merge_results(target, result):
    combined = {}
    for group in ('review_jobs', 'jobs'):
        for job in target[group] + result.get(group, []):
            identity = tuple(matching.normalize(job.get(key, '')) for key in ('title', 'company', 'location'))
            old = combined.get(identity)
            if old:
                job['sources'] = list(dict.fromkeys(old.get('sources', [old['source']]) + job.get('sources', [job['source']])))
            combined[identity] = job
    target['jobs'] = [job for job in combined.values() if job['salary_check']['status'] == 'eligible'][:500]
    target['review_jobs'] = [job for job in combined.values() if job['salary_check']['status'] == 'review'][:500]
    target['reports'].extend(result.get('reports', []))
    target['research_sources'].extend(result.get('research_sources', []))
    for key in ('query_plan', 'search_suggestions', 'google_url', 'coverage'):
        if result.get(key):
            target[key] = result[key]
    for key in ('time_limited', 'budget_limited'):
        target[key] = target.get(key, False) or result.get(key, False)


def search(filters, companies, usage, user_id, collect):
    from .providers import google_url
    decisions = []
    result = {'jobs': [], 'review_jobs': [], 'reports': [], 'research_sources': [], 'google_url': google_url(filters),
              'coverage': 'Seleção automática respeita perfil, localização e salário. Nenhuma fonte garante cobertura completa.'}
    status = resources(filters, companies, usage, user_id)
    # Fontes escolhidas têm prioridade. Cache é tentado mesmo com cota esgotada.
    selected = sorted(filters['sources'], key=lambda name: ['jooble', 'companies', 'google', 'gemini'].index(name))
    order = list(dict.fromkeys(selected + ['companies', 'jooble', 'google']))
    if status['gemini']['auto_enabled'] and status['gemini']['search_available']:
        order = list(dict.fromkeys(order + ['gemini']))
    substituted, stopped = False, False
    for source in order:
        info = status[source]
        automatic_ai = source == 'gemini' and (source not in selected or os.getenv('GEMINI_ENABLED', 'false') != 'true')
        if not info['configured'] or (source == 'gemini' and (info['blocked'] or automatic_ai and not info['auto_enabled'])):
            decisions.append({'source': source, 'status': 'unavailable', 'note': 'Fonte sem configuração, permissão ou saldo disponível.'})
            continue
        if source == 'gemini' and automatic_ai and not info['search_available']:
            continue
        cached_only = source in {'jooble', 'google'} and info.get('blocked', False)
        query = {**filters, 'sources': [source], 'auto_sources': False, '_cache_only': cached_only, '_skip_ai_ranking': True}
        try:
            http.checkpoint()
            with gemini.usage_scope(usage, user_id, automatic=automatic_ai):
                received = collect(query, companies, usage=usage, user_id=user_id)
        except http.SearchDeadlineExceeded:
            result['time_limited'] = True
            break
        merge_results(result, received)
        usable = len(received.get('jobs', [])) + len(received.get('review_jobs', []))
        failure = next((report['status'] for report in received.get('reports', []) if report['status'] in {'limited', 'error', 'pending'}), None)
        decisions.append({'source': source, 'status': 'cache' if cached_only and usable else 'used' if usable else failure or 'empty',
                          'note': 'Cache de 24 horas, sem nova chamada.' if cached_only and usable else 'Sem nova chamada: cota ou pausa ativa; cache sem oportunidades compatíveis.' if cached_only else 'Fonte indisponível ou limitada; próxima alternativa será avaliada.' if failure else 'Fonte consultada dentro dos limites disponíveis.',
                          'opportunities': usable, 'substitute': source not in selected})
        substituted = substituted or source not in selected
        # Um resultado útil encerra a troca; não consumimos todas as fontes por rotina.
        if usable:
            stopped = True
            break
        if received.get('time_limited'):
            break
    alternative = guidance(filters, companies)
    activities = [{'id': 'favorites', 'name': 'Rever oportunidades salvas', 'url': '/#favorites'},
                  {'id': 'history', 'name': 'Retomar resultados anteriores', 'url': '/#history'}]
    activities += [{'id': f'link-{index}', **item} for index, item in enumerate(alternative['links'])]
    saved = saved_opportunities(filters, usage, user_id) if not stopped else []
    ai_note = ''
    if not stopped and status['gemini']['configured'] and status['gemini']['auto_enabled']:
        try:
            http.checkpoint()
            # Sem pesquisa Google: orientação com fatos e links já conhecidos, nunca vagas inventadas.
            prompt = ('Organize atividades para procurar emprego enquanto APIs estão indisponíveis. Use somente os IDs fornecidos. '
                      'Não invente vagas, URLs, salários, requisitos ou experiência da pessoa. Não afirme que anúncios antigos ainda estão abertos. '
                      'Retorne JSON {"action_ids":["id"],"tips":["dica curta em português"]}, até cinco atividades e três dicas. Dados: '
                      + json.dumps({'profile': filters['profile'], 'terms': filters['keywords'], 'country': filters['country'],
                                    'activities': activities[:20], 'saved_opportunities': saved[:10]}, ensure_ascii=False))
            with gemini.usage_scope(usage, user_id, automatic=True):
                advice, _ = gemini.generate(prompt)
            ids = advice.get('action_ids', [])
            known = {item['id']: item for item in activities}
            preferred = [known[item] for item in ids[:5] if isinstance(item, str) and item in known] if isinstance(ids, list) else []
            activities = list({item['id']: item for item in preferred + activities}.values())
            tips = advice.get('tips', [])
            if isinstance(tips, list):
                alternative['tips'] = [item[:500] for item in tips[:3] if isinstance(item, str)] + alternative['tips']
            ai_note = 'Gemini organizou atividades com dados disponíveis; não realizou pesquisa Google nesta orientação.'
            decisions.append({'source': 'gemini', 'status': 'assistance', 'note': ai_note})
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            # Erros de rede também são tratados pelo requests; nenhuma atividade se perde.
            from .usage import BudgetExceeded
            ai_note = str(exc) if isinstance(exc, (BudgetExceeded, gemini.GeminiError)) else 'Orientação Gemini indisponível; atividades sem IA continuam prontas.'
            decisions.append({'source': 'gemini', 'status': 'limited' if isinstance(exc, BudgetExceeded) else 'unavailable', 'note': ai_note})
        except gemini.requests.RequestException:
            ai_note = 'Orientação Gemini indisponível; atividades sem IA continuam prontas.'
    current = resources(filters, companies, usage, user_id)
    resets = []
    for item in current.values():
        if not item.get('configured') or not item.get('blocked'):
            continue
        renewal = datetime.fromisoformat(item['resets_at']).timestamp() if item.get('resets_at') and (not item.get('remaining_today') or item.get('token_remaining', 512) < 512) else 0
        available = max(renewal, item.get('blocked_until', 0))
        if available > usage.clock():
            resets.append(datetime.fromtimestamp(available).astimezone().isoformat())
    result['routing'] = {'mode': 'automatic', 'state': 'results' if stopped else 'activities', 'substituted': substituted,
                         'decisions': decisions, 'resources': current, 'next_reset': min(resets, key=lambda value: datetime.fromisoformat(value).timestamp()) if resets else None,
                         'activities': activities, 'tips': alternative['tips'], 'saved_opportunities': saved, 'ai_note': ai_note}
    return result
