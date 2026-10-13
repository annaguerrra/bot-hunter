"""Orientações editoriais e exercícios pessoais; nenhuma chamada externa."""
import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from .matching import normalize

CATEGORIES = {'linkedin': 'LinkedIn e imagem', 'curriculo': 'Currículo',
              'entrevista': 'Entrevistas', 'networking': 'Networking e planejamento'}
CHECKLIST = [
    {'id': 'photo', 'label': 'Foto atual, nítida e com aparência profissional'},
    {'id': 'headline', 'label': 'Título com minha especialidade e cargo desejado'},
    {'id': 'summary', 'label': 'Resumo com trajetória, competências e objetivos'},
    {'id': 'results', 'label': 'Experiências com entregas e resultados reais'},
    {'id': 'skills', 'label': 'Competências relevantes para os cargos que busco'},
    {'id': 'education', 'label': 'Formação e certificações atualizadas'},
    {'id': 'recommendations', 'label': 'Recomendações de pessoas com quem trabalhei'},
    {'id': 'alerts', 'label': 'Alertas de vagas por cargo e localidade'},
    {'id': 'location', 'label': 'Localização e preferências de trabalho revisadas'},
    {'id': 'network', 'label': 'Contatos e conversas com profissionais da área'},
]
QUESTIONS = [
    {'id': 'process', 'text': 'Conte sobre uma situação em que melhorou um processo.'},
    {'id': 'problem', 'text': 'Como você resolveu um problema difícil com sua equipe?'},
    {'id': 'priority', 'text': 'Quando precisou organizar prioridades e cumprir um prazo?'},
    {'id': 'learning', 'text': 'O que aprendeu com uma situação que não saiu como esperava?'},
]


def validate_resources(data):
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('resources'), list):
        raise ValueError('Arquivo de conteúdos inválido.')
    seen = set()
    for item in data['resources']:
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key] for key in ('id', 'title', 'summary', 'action', 'source_name', 'source_url', 'locale')):
            raise ValueError('Recurso incompleto.')
        parts = urlsplit(item['source_url'])
        if (item.get('category') not in CATEGORIES or parts.scheme != 'https' or parts.username or parts.password
                or parts.hostname not in {'www.linkedin.com', 'careerservices.fas.harvard.edu', 'capd.mit.edu'}
                or parts.port not in (None, 443) or item['id'] in seen
                or not isinstance(item.get('tags'), list) or not all(isinstance(tag, str) for tag in item['tags'])):
            raise ValueError('Fonte ou categoria inválida.')
        seen.add(item['id'])
    return data['resources']


@lru_cache(maxsize=1)
def resources():
    path = Path(__file__).resolve().parents[1] / 'resources/career_resources.json'
    return validate_resources(json.loads(path.read_text(encoding='utf-8')))


def list_resources(category='', q='', profile=''):
    if category and category not in CATEGORIES or len(q) > 100 or profile not in {'', 'both', 'product', 'production', 'custom'}:
        raise ValueError('Filtros de carreira inválidos.')
    items = [dict(item, category_name=CATEGORIES[item['category']]) for item in resources()
             if (not category or item['category'] == category)
             and (not q or normalize(q) in normalize(' '.join([item['title'], item['summary'], *item['tags']])))]
    # O perfil prioriza exemplos editoriais; não analisamos o LinkedIn da pessoa.
    preferred = 'produto' if profile == 'product' else 'processos' if profile == 'production' else ''
    return sorted(items, key=lambda item: bool(preferred and preferred in normalize(' '.join(item['tags']))), reverse=True)


def validate_progress(body):
    if not isinstance(body, dict):
        raise ValueError('Progresso inválido.')
    checklist, star = body.get('checklist', []), body.get('star', {})
    valid = {item['id'] for item in CHECKLIST}
    if not isinstance(checklist, list) or len(checklist) > len(valid) or any(not isinstance(item, str) or item not in valid for item in checklist):
        raise ValueError('Checklist inválido.')
    if not isinstance(star, dict) or star.get('question', 'process') not in {item['id'] for item in QUESTIONS}:
        raise ValueError('Pergunta de entrevista inválida.')
    if any(not isinstance(star.get(key, ''), str) or len(star.get(key, '')) > 3000 for key in ('situation', 'task', 'action', 'result')):
        raise ValueError('Use até 3.000 caracteres em cada resposta STAR.')
    return {'checklist': list(dict.fromkeys(checklist)), 'star': {'question': star.get('question', 'process'),
            **{key: star.get(key, '') for key in ('situation', 'task', 'action', 'result')}}}
