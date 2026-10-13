# Empresas verificadas para engenharia de produto e produção

Verificação em **12/10/2026**, usando páginas oficiais de recrutamento e a API pública SmartRecruiters. As quatro empresas abaixo foram adicionadas ao catálogo inicial além da Bosch. Cada conta pode pausar, remover ou cadastrar outras empresas sem afetar as demais.

| Empresa | Página de carreiras cadastrada | Exemplo público compatível |
|---|---|---|
| Continental / ContiTech | [Carreiras](https://careers.smartrecruiters.com/ContinentalGroupSectorContiTech) | [Process and Product Engineer](https://jobs.smartrecruiters.com/ContinentalGroupSectorContiTech/744000143548861-process-and-product-engineer) |
| BEUMER Group | [Carreiras](https://careers.smartrecruiters.com/BEUMERGroup1) | [Mechanical Design Engineer](https://jobs.smartrecruiters.com/BEUMERGroup1/744000131608659) |
| Renesas Electronics | [Carreiras](https://careers.smartrecruiters.com/RenesasElectronics) | [Manufacturing Engineer](https://jobs.smartrecruiters.com/RenesasElectronics/744000152071139-manufacturing-engineer) |
| Sika | [Carreiras](https://careers.smartrecruiters.com/SikaAG) | [Engenheiro de Produto PL](https://jobs.smartrecruiters.com/SikaAG/744000149359979) |

A verificação inicial encontrou títulos compatíveis nas quatro fontes. Uma busca posterior pelo painel, em todas as cinco empresas, retornou **3 vagas com salário compatível** e **93 vagas para análise**, com as cinco fontes respondendo. Esses números são uma fotografia da consulta, e mudam conforme filtros, idioma, país, paginação e publicação dos anúncios.

O salário mínimo de R$ 7.000 mensais continua sendo conferido por anúncio. Empresas com vagas compatíveis não garantem esse valor: salários desconhecidos ficam para análise e não recebem alertas.

A SEGULA foi pesquisada, mas a fonte SmartRecruiters consultada não retornou anúncios ativos na consulta de verificação; por isso ela não foi incluída como fonte confirmada.

## Descoberta pela interface

Em **Empresas → Descobrir empresas**, o catálogo público é separado do radar de cada conta. Contas antigas e novas veem as sugestões sem novo seed: empresas pausadas ou removidas permanecem assim. Os filtros de nome, plataforma, área, país, região e abrangência consultam somente o catálogo local, paginado em dez cards. Cadastre individualmente ou selecione até vinte itens por lote. O cadastro é idempotente por proprietário e plataforma/tenant ou URL; duplicações não reativam empresas pausadas e nenhum cadastro inicia uma busca.

**Verificar sugestões** usa os cargos e locais de **Explorar vagas**, prioriza o perfil e país e consulta até cinco portais por página. **Verificar próximas empresas** percorre outras candidatas sem repetir sempre as primeiras. A consulta utiliza os ATS públicos e cache de 12 horas, sem Jooble, SerpAPI ou Gemini por padrão. Ativar **Também pesquisar novas empresas com Gemini** é uma escolha separada, sujeita às permissões e cotas existentes. URLs sugeridas pela IA precisam constar nas fontes citadas; anúncios públicos compatíveis são verificados antes de sugerir cadastro. O modo explícito Somente empresas impede o uso de IA mesmo nessa verificação.

O catálogo não apresenta contagens de vagas compatíveis sem consulta. A descoberta mostra anúncios encontrados para os filtros, sem assegurar salário elegível. Uma API com zero resultados não prova que a empresa deixou de contratar. Abrangência internacional é uma indicação do portal, não uma lista de países com oportunidades atuais.

## Expansão opcional: quinze integrações verificadas

Em **12/10/2026**, foram realizadas **15 consultas diretas** aos endpoints públicos abaixo, sem chaves e sem chamadas Jooble, SerpAPI ou Gemini. Todas retornaram o formato esperado; nenhuma candidata ficou pendente nessa verificação. A disponibilidade pode mudar. O número abaixo é o tamanho da resposta de verificação, **antes de filtros de área, país e salário**. SmartRecruiters e Lever foram consultados com `limit=1`; Greenhouse e Ashby devolvem o board.

| Empresa | Plataforma / tenant | Abrangência indicativa | Anúncios devolvidos na verificação |
|---|---|---|---:|
| SGS | SmartRecruiters / `SGS` | Internacional, incluindo Brasil | 1 (amostra) |
| Continental | SmartRecruiters / `Continental` | Internacional | 1 (amostra) |
| Eurofins | SmartRecruiters / `Eurofins` | Internacional | 1 (amostra) |
| O-I Glass | SmartRecruiters / `O-I` | Internacional | 1 (amostra) |
| TRIGO Group | SmartRecruiters / `Trigo` | Internacional | 1 (amostra) |
| QIMA | SmartRecruiters / `QIMA` | Internacional | 1 (amostra) |
| Turner & Townsend | SmartRecruiters / `TurnerTownsend` | Internacional | 1 (amostra) |
| Exowatt | Lever / `exowatt` | Estados Unidos | 1 (amostra) |
| Rigetti Computing | Lever / `rigetti` | Estados Unidos | 1 (amostra) |
| Divergent Technologies | Greenhouse / `divergent` | Estados Unidos | 126 |
| Hadrian | Ashby / `hadrian-automation` | Estados Unidos | 130 |
| Collaborative Robotics | Ashby / `cobot` | Estados Unidos | 13 |
| Eli Health | Ashby / `eli` | Canadá | 5 |
| MatX | Ashby / `matx` | Estados Unidos | 45 |
| First Order Effects | Ashby / `firstordereffects` | Estados Unidos | 15 |

Continental e Continental / ContiTech usam tenants diferentes; o catálogo preserva ambos. **SpaceX, Anduril e Path Robotics** são somente links externos: não ativamos automaticamente os antigos boards Greenhouse. Seu adapter atual precisa de identificação e validação antes de entrar no radar pelo catálogo.

O catálogo contém **20 integrações** (cinco iniciais + quinze opcionais) e **três links externos**. Os JSONs editoriais ficam em `resources/`, incluídos no deploy. `data/` continua excluído do pacote Vercel por conter arquivos privados locais. Os registros usam `validated`, `api_pending` ou `manual_only`; itens pendentes e links externos têm cadastro pelo catálogo bloqueado.

### Endpoints e revalidação

- SmartRecruiters: `https://api.smartrecruiters.com/v1/companies/{tenant}/postings?limit=1&destination=PUBLIC`.
- Greenhouse: `https://boards-api.greenhouse.io/v1/boards/{tenant}/jobs`.
- Lever: `https://api.lever.co/v0/postings/{tenant}?mode=json&limit=1`.
- Ashby: `https://api.ashbyhq.com/posting-api/job-board/{tenant}?includeCompensation=true`, conforme a [documentação oficial](https://developers.ashbyhq.com/docs/public-job-posting-api).

O adapter Ashby consulta uma vez por empresa, ignora anúncios não listados, normaliza localidades secundárias e remuneração base. Salário anual é dividido por doze; períodos desconhecidos, valores estimados ou faixas sem localização definida permanecem para análise. Bônus e participação não contam como salário. Remoto não significa contratação em todos os países. Nenhuma regra de alertas ou deduplicação foi relaxada.

Validação opcional (acessa os ATS públicos; no máximo vinte endpoints e com timeout, limite de resposta e validação de redirecionamentos):

```powershell
python scripts/validate_candidate_ats.py --catalog resources/companies.json --limit 15
```

O comando não cadastra empresas, não muda status do catálogo e não consome APIs de busca. Revise o resultado e atualize a data/status do registro manualmente quando necessário.
