"""Identidade persistente das vagas, independente da fonte que as encontrou."""
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from .matching import normalize


def identity(job):
    # Título, empresa e local normalizados unem anúncios equivalentes entre fontes.
    company = normalize(job.get('company', ''))
    parts = [normalize(job.get(field, '')) for field in ('title', 'company', 'location')]
    if not company or company in {'confidencial', 'confidential', 'empresa nao informada'}:
        # Empresas anônimas não são agrupadas apenas por título e cidade.
        url = urlsplit(job.get('link', ''))
        query = [(key, value) for key, value in parse_qsl(url.query) if not key.lower().startswith('utm_') and key.lower() not in {'gclid', 'fbclid'}]
        parts.append(urlunsplit((url.scheme.lower(), url.netloc.lower(), url.path, urlencode(query), '')))
    return 'job_' + hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


def remember(db, job, user_id):
    signature = identity(job)
    original = str(job.get('id', signature))
    known = db.execute('SELECT job_id FROM job_aliases WHERE user_id=? AND source_id=?', (user_id, original)).fetchone()
    identifier = known['job_id'] if known else 'job_' + hashlib.sha256(original.encode()).hexdigest()
    if not known:
        candidates = db.execute('SELECT id,payload FROM job_index WHERE user_id=? AND signature=?', (user_id, signature)).fetchall()
        # Só unimos fontes diferentes quando existe uma correspondência inequívoca.
        # Duas posições do mesmo cargo na mesma empresa permanecem separadas.
        if len(candidates) == 1:
            candidate = json.loads(candidates[0]['payload'])
            if job.get('source') not in candidate.get('sources', [candidate.get('source')]):
                identifier = candidates[0]['id']
    saved = db.execute('SELECT payload FROM job_index WHERE user_id=? AND id=?', (user_id, identifier)).fetchone()
    previous = json.loads(saved['payload']) if saved else {}
    sources = list(dict.fromkeys(previous.get('sources', [previous.get('source')]) + job.get('sources', [job.get('source')])))
    merged = {**previous, **job, 'id': original, 'canonical_id': identifier, 'sources': [source for source in sources if source]}
    db.execute('INSERT INTO job_index VALUES(?,?,?,?) ON CONFLICT(user_id,id) DO UPDATE SET payload=excluded.payload',
               (user_id, identifier, json.dumps(merged), signature))
    db.execute('INSERT INTO job_aliases VALUES(?,?,?) ON CONFLICT(user_id,source_id) DO UPDATE SET job_id=excluded.job_id',
               (user_id, original, identifier))
    return merged


def resolve(db, identifier, user_id):
    row = db.execute('SELECT job_id FROM job_aliases WHERE user_id=? AND source_id=?', (user_id, identifier)).fetchone()
    return row['job_id'] if row else identifier
