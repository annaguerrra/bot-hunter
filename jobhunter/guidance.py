"""Sugestões pessoais sem consultar IA nem consumir chamadas dos provedores."""
from urllib.parse import urlencode
from .geo import BY_CODE


def guidance(filters, companies):
    terms = filters['keywords']
    destination = ', '.join(part for part in (filters.get('city'), filters.get('state'),
                            BY_CODE.get(filters.get('country'), {}).get('english')) if part) or 'Worldwide'
    keywords = ' OR '.join(terms)
    return {'links': [
        {'name': 'LinkedIn · procurar vagas', 'url': 'https://www.linkedin.com/jobs/search/?' + urlencode({'keywords': keywords, 'location': destination})},
        {'name': 'Google Empregos · explorar diretamente', 'url': 'https://www.google.com/search?' + urlencode({'q': keywords + ' jobs ' + destination, 'udm': '8'})},
        {'name': 'Páginas de carreira · descobrir sites', 'url': 'https://www.google.com/search?' + urlencode({'q': keywords + ' careers ' + destination + ' -site:jooble.org'})},
    ] + [{'name': company['name'] + ' · carreiras', 'url': company['url']} for company in companies if company['enabled']],
    'tips': [
        'Revise primeiro as vagas salvas e as vagas Para análise. Abra o anúncio original e confirme salário, requisitos e data antes de se candidatar.',
        'No LinkedIn, procure cada cargo separadamente em português, inglês e no idioma do país.' + (' Para engenharia de produto, tente product engineer, product development engineer e mechanical design engineer.' if filters.get('profile') != 'custom' else ' Use os nomes locais da sua profissão e confira se a descrição corresponde à sua especialidade.'),
        'Salve a pesquisa no LinkedIn e ative alertas. Combine cargo, país, remoto e publicação recente para reduzir resultados irrelevantes.',
        'Ajuste o título e o resumo do perfil com sua especialidade e competências comprováveis. Destaque resultados, ferramentas e projetos relevantes no currículo.',
        'Mantenha uma lista das candidaturas, data, link e contato. Priorize oportunidades compatíveis e personalize a candidatura.',
        'Visite diretamente as páginas de carreira das empresas. Estes links e o histórico não gastam consultas da Jooble dentro do Bot Hunter.'
    ]}
