# Bot Hunter — vagas e oportunidades globais

O projeto agora tem uma **interface web local**, além do bot original de Telegram/e-mail. É possível buscar por região do mundo, país, estado/província e cidade, cadastrar empresas, salvar vagas, retomar buscas e enviar oportunidades selecionadas.

## Abrir a aplicação web

Na pasta do projeto, execute:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Somente se você ainda não tem .env:
Copy-Item .env.example .env
.\.venv\Scripts\python.exe web.py
```

Abra **http://127.0.0.1:5000**. O processo precisa continuar rodando enquanto você usa a interface. Para usar outra porta: `python web.py --port 5001`.

O backend escuta apenas no computador local e agora possui **cadastro e login com dados separados por usuário**. A primeira conta criada será administradora e receberá o histórico existente; suas chaves atuais continuam salvas. As demais contas têm preferências, favoritos, empresas, histórico e destinatários próprios. Consulte o [guia de contas e preparação para hospedagem](docs/accounts.md). As chaves de pesquisa compartilhadas só podem ser alteradas pela administração e não são devolvidas pela API.

### Busca internacional

- **Mundo todo, Américas, Europa, Ásia, África, Oceania e Antártida**; catálogo ISO de 249 países/territórios.
- Países filtrados pela região escolhida; estados e províncias carregados conforme o país.
- Até 3 termos por busca, separados por `;`. Exemplos: `production engineer;manufacturing engineer;engenheiro de produção`.
- Por padrão, um desses termos precisa aparecer no título. Desmarque essa opção para uma busca mais ampla. Para outros destinos, acrescente o termo no idioma local.
- Filtro de remoto, termos excluídos, ordenação e páginas por fonte.
- O botão **Encontrar oportunidades** busca nas fontes selecionadas e nas empresas ativas do seu radar. Adicionar uma empresa a cadastra para essas buscas; isso não cria um agendamento automático novo.
- Os resultados informam fonte, localização, cobertura e eventuais erros por fonte. Fontes com erro não anulam as outras.

### Páginas de empresas

A Bosch, **Continental/ContiTech, BEUMER Group, Renesas Electronics e Sika** vêm cadastradas e usam fontes públicas SmartRecruiters. Vagas compatíveis foram verificadas nas quatro empresas adicionadas; consulte os [sites e exemplos verificados](docs/verified-companies.md). Em **Empresas → Descobrir empresas**, Gemini ajuda a encontrar páginas de carreira a partir de seus filtros; fontes citadas e anúncios compatíveis são conferidos antes de sugerir o cadastro. O catálogo público é usado quando a IA está indisponível. Você também pode cadastrar sua URL de carreiras manualmente. As plataformas são reconhecidas automaticamente:

| Fonte | URL de exemplo | Como funciona |
|---|---|---|
| Bosch | `https://careers.bosch.com/` | API SmartRecruiters, empresa `BoschGroup` |
| SmartRecruiters | `https://jobs.smartrecruiters.com/EMPRESA` | Publicações públicas, busca e paginação |
| Greenhouse | `https://job-boards.greenhouse.io/EMPRESA` | API pública de Job Board |
| Lever | `https://jobs.lever.co/EMPRESA` | API pública de Postings |
| Outros sites | Página pública de carreiras/vagas | Detecta links para as plataformas acima ou lê anúncios estruturados `JobPosting` |

Também são aceitas as variantes europeias do Greenhouse e Lever. Sites genéricos têm leitura limitada à página cadastrada e até 9 links de vagas do mesmo domínio, respeitando `robots.txt`. Páginas que exigem login, execução de JavaScript ou não fornecem anúncios estruturados podem não ser compatíveis. Nesses casos, cadastre a página da plataforma de vagas da empresa. Não existe garantia de compatibilidade com qualquer website.

### Google Empregos

Na tela **Integrações**, informe sua chave [SerpAPI](https://serpapi.com/manage-api-key). Ela é salva em `SERPAPI_API_KEY` no `.env` privado. A busca usa o mecanismo `google_jobs`, geografia, idioma e a paginação `next_page_token` documentados pela SerpAPI. Essa integração é de terceiros e depende da cobertura e da cota da sua conta.

Sem essa chave, **Abrir no Google Empregos** abre a interface do Google com os termos e o destino escolhidos. Esse link não importa vagas para o painel nem para os alertas. Buscas de região/mundo via SerpAPI consultam até 2 mercados prioritários por execução; escolher um país direciona a busca a ele.

### Jooble internacional

**Cada país da Jooble exige uma chave própria**, segundo a [documentação oficial](https://jooblehelpcenter.freshdesk.com/en/support/solutions/articles/60001448238-rest-api-documentation). A chave original `JOOBLE_API_KEY` é associada ao Brasil por padrão (`JOOBLE_COUNTRY=BR`). Cadastre as outras chaves em **Integrações → Jooble por país**; elas são salvas como `JOOBLE_API_KEY_DE`, `JOOBLE_API_KEY_US` etc.

```dotenv
JOOBLE_COUNTRY=BR
JOOBLE_API_KEY=sua_chave_brasileira
# Opcional, obtida em https://de.jooble.org/api/about:
JOOBLE_API_KEY_DE=sua_chave_alema
WEB_MAX_MARKET_QUERIES=6
```

A aplicação envia cada chave somente ao endpoint regional correspondente. Sem a chave do país selecionado, a interface mostra a configuração pendente e mantém as outras fontes. Para mundo/região, consulta os países configurados, com até `WEB_MAX_MARKET_QUERIES` chamadas por busca. A primeira página de cada combinação cargo/país é usada para preservar a cota.

### Vagas salvas, histórico e alertas

O coração salva uma oportunidade. O **Histórico** guarda resultados e filtros; **Ver resultados** retoma os dados já coletados e **Usar filtros** prepara uma nova busca. Os registros ficam no SQLite local `data/hunter.sqlite`, ignorado pelo Git.

Selecione até **100 vagas**, clique em **Enviar alertas** e escolha Telegram/e-mail. Buscas não enviam mensagens automaticamente. O Telegram divide os resultados em mensagens menores que seu limite e espaça os envios: 1,1 segundo em chats pessoais e 3,1 segundos em grupos. Respostas 429 com `retry_after` de até 60 segundos recebem até duas novas tentativas; erros ambíguos de rede não são reenviados automaticamente. O histórico de envio da interface é separado por usuário e canal: se um canal falha, o que funcionou não repete as vagas. O histórico da interface é independente do JSON utilizado pelo bot CLI original. [Limites Telegram](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this).

Em **Explorar vagas → Vagas por consulta Jooble**, escolha 20, 50 ou **100** resultados (padrão). Isso altera `ResultOnPage`, mantendo o limite de chamadas por busca. A API pode devolver menos anúncios; filtros, duplicidade e remuneração reduzem a lista aprovada. A CLI também solicita até 100 resultados por chamada e aceita `MAX_JOBS` entre 1 e 100; valores já presentes no `.env` continuam sendo respeitados. Mais resultados aumentam o volume processado e o tempo de envio, sem transformar cada anúncio em uma consulta adicional. [Parâmetros Jooble](https://help.jooble.org/en/support/solutions/articles/60001448238-rest-api-documentation).

### Cobertura e limites

As fontes têm cobertura, ordenação e limites próprios. **Mundo todo** permite anúncios de qualquer país, mas não significa coletar todas as vagas existentes. Aumente as páginas, pesquise países específicos e cadastre novas empresas para ampliar a cobertura. Quando um agregador não informa o país, o país da consulta é indicado no cartão; para fontes de empresas, países desconhecidos são excluídos quando existe um filtro geográfico. Estados/cidades precisam constar na localização do anúncio para passar pelos filtros.

### Arquitetura e testes

| Arquivo | Função |
|---|---|
| `web.py` | Backend Flask, endpoints, validação, busca assíncrona e alertas |
| `templates/index.html`, `static/` | Frontend responsivo em português |
| `jobhunter/providers.py` | SmartRecruiters, Greenhouse, Lever, JobPosting, Jooble regional e SerpAPI |
| `jobhunter/geo.py`, `jobhunter/continents.json` | Países, subdivisões e regiões |
| `jobhunter/storage.py` | Empresas, buscas, favoritas e envios em SQLite |
| `main.py` | Bot original e integrações de Telegram/e-mail reutilizadas |
| `tests/test_web.py` | Contratos de geografia, provedores, persistência e API |

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check static/app.js
# QA opcional em Edge, com web.py já rodando (consulta vagas reais da Bosch):
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/check_ui.py
```

O QA não envia notificações nem altera credenciais. Capturas e relatório ficam em `logs/qa/`, ignorado pelo Git. APIs e envios são simulados nos testes unitários.

Referências das fontes: [SmartRecruiters Posting API](https://developers.smartrecruiters.com/reference/v1listpostings), [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html), [Lever Postings API](https://github.com/lever/postings-api), [SerpAPI Google Jobs](https://serpapi.com/google-jobs-api). O mapa de continentes foi derivado do [GeoNames countryInfo](https://download.geonames.org/export/dump/), licenciado em CC BY 4.0. Países e subdivisões são fornecidos pelo pycountry/ISO.

---

## Bot original de linha de comando

Bot em **Python** para buscar vagas pela API da Jooble, filtrar oportunidades e enviar os links por **Telegram e e-mail**. Os dois canais podem funcionar juntos ou separadamente.

O foco deste MVP é **ser fácil de entender e personalizar**: quase tudo que você altera fica no `.env`, enquanto a lógica permanece no `main.py` (comentado em português).

## 1. Como funciona

```text
Execução manual ou GitHub Actions
              |
              v
        API da Jooble
              |
              v
     Filtros de vagas
              |
              v
    Histórico por canal
       /            \
      v              v
  Telegram         E-mail
      |              |
      +------v-------+
       Atualiza histórico
```

**Por que o histórico é separado?** Se o Telegram funcionar e o envio do Gmail falhar, a vaga é marcada como entregue **apenas no Telegram**. Na próxima execução, o bot tenta enviar somente o e-mail pendente, sem repetir o Telegram.

### Estrutura

```text
job-hunter-bot/
├── main.py                       # Busca, filtros, e-mail e Telegram (comentado)
├── .env.example                  # Configurações que você pode personalizar
├── .env                          # SEU arquivo privado (não vai para o Git)
├── .gitignore
├── requirements.txt
├── data/
│   └── sent_jobs.json            # IDs enviados por Telegram e e-mail
├── tests/
│   └── test_main.py              # Testes automáticos que não enviam nada
└── .github/workflows/
    └── job-alerts.yml            # Agendamento no GitHub
```

## 2. Instalar e configurar

Requer Python 3.10 ou mais recente. No terminal **PowerShell**, abra a pasta do projeto:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Agora abra o `.env`. **Não altere o `.env.example` com suas senhas**, porque ele será versionado como exemplo no GitHub.

### 2.1 Chave de busca: Jooble

Solicite uma chave em <https://br.jooble.org/api/about> e preencha:

```ini
JOOBLE_API_KEY=SUA_CHAVE
```

A chave gratuita tem limite de chamadas: ajuste a quantidade de pesquisas antes de automatizar.

### 2.2 Telegram

1. Abra <https://t.me/BotFather> e crie um bot com `/newbot`.
2. Preencha `TELEGRAM_BOT_TOKEN` no `.env`.
3. Seu pai deve abrir o bot e enviar `/start` para que ele consiga receber mensagens privadas.
4. Execute `python main.py --chat-id` e copie o ID da conversa dele para `TELEGRAM_CHAT_ID`.
5. Execute `python main.py --test-telegram` para verificar o envio.

```ini
SEND_TELEGRAM=true
TELEGRAM_BOT_TOKEN=TOKEN_RECEBIDO_NO_BOTFATHER
TELEGRAM_CHAT_ID=ID_DO_CHAT_DO_DESTINATARIO
```

### 2.3 E-mail com Gmail (SMTP)

Para começar, usamos **SMTP com SSL**. Não precisa criar uma segunda API nem adicionar dependências Python: o envio usa a biblioteca `smtplib` do próprio Python.

1. Escolha o Gmail **remetente** (`EMAIL_FROM`). Pode ser o seu e-mail.
2. Informe o Gmail **destinatário** (`EMAIL_TO`). Pode ser o do seu pai. Para enviar para mais de uma pessoa, separe por `;`.
3. Na conta remetente, ative a **verificação em duas etapas**.
4. Acesse <https://myaccount.google.com/apppasswords> para gerar uma **senha de aplicativo**, caso a opção esteja disponível.
5. Coloque essa senha em `EMAIL_APP_PASSWORD`. **Não use sua senha normal do Gmail**.
6. Execute `python main.py --test-email` para enviar um teste sem consumir a Jooble.

```ini
SEND_EMAIL=true
EMAIL_FROM=seuemail@gmail.com
EMAIL_TO=emaildopai@gmail.com
EMAIL_APP_PASSWORD=SENHA_DE_APLICATIVO
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
```

**Importante:** certas contas corporativas, educacionais ou com proteções adicionais não permitem criar senhas de aplicativo. O Google recomenda OAuth (“Fazer login com Google”) para integrações mais robustas. O MVP usa senha de aplicativo por simplicidade, se estiver disponível. Para outros provedores SMTP, ajuste `SMTP_HOST` e `SMTP_PORT`; esta versão usa **SSL direto**, portanto a porta padrão é **465** (não STARTTLS/587).

Ajuda oficial: <https://support.google.com/accounts/answer/185833> e <https://developers.google.com/workspace/gmail/imap/imap-smtp?hl=pt-BR>.

### 2.4 Ativar os canais

Deixe **os dois ligados** para enviar as vagas por e-mail e Telegram:

```ini
SEND_TELEGRAM=true
SEND_EMAIL=true
```

Se algum dia quiser usar apenas um, troque o outro para `false`. Os históricos continuam separados.

## 3. Personalização de cargos, cidades e filtros

Tudo no `.env`:

| Variável | O que você altera | Exemplo |
|---|---|---|
| `JOB_KEYWORDS` | Cargos pesquisados (separados por `;`) | `engenheiro de produção;coordenador de produção` |
| `JOB_LOCATION` | Cidade principal | `Curitiba` |
| `JOB_LOCATIONS` | Várias cidades; substitui `JOB_LOCATION` se preenchida | `Curitiba;Ponta Grossa` |
| `JOB_RADIUS` | Distância em km (0, 4, 8, 16, 26, 40, 80) | `80` |
| `EXCLUDED_TITLE_TERMS` | Palavras que bloqueiam vagas | `estágio;estagiário;aprendiz` |
| `REQUIRED_TITLE_TERMS` | Exige pelo menos um termo no título (opcional) | `engenheiro;coordenador` |
| `EXCLUDED_COMPANIES` | Empresas que você não quer ver (opcional) | `Empresa A;Empresa B` |
| `MAX_JOBS` | Vagas novas por canal por execução na CLI (1 a 100) | `100` |
| `MAX_QUERIES_PER_RUN` | Limite de chamadas à Jooble por execução | `4` |

**Consumo de API:** cada combinação **cargo × cidade** gera uma consulta à Jooble. Por exemplo, 2 cargos × 1 cidade = 2 requisições por execução. O `--plan` mostra a conta **sem chamar a API**.

## 4. Comandos úteis

```powershell
# Mostra quais buscas serão feitas, sem gastar API nem enviar mensagens.
python main.py --plan

# Obtém o chat ID do Telegram (não consulta a Jooble).
python main.py --chat-id

# Testa APENAS o Telegram (não consulta a Jooble).
python main.py --test-telegram

# Testa APENAS o e-mail (não consulta a Jooble).
python main.py --test-email

# Busca vagas e mostra o resultado no terminal para CADA canal.
# NÃO envia mensagens nem salva histórico; MAS consome chamadas à Jooble.
python main.py --preview

# Busca vagas novas, envia pelos canais ligados e salva os IDs enviados.
python main.py

# Executa testes simulados, sem API nem envio real.
python -m unittest discover -s tests -v
```

Ordem recomendada: `--plan` → `--chat-id` → `--test-telegram` → `--test-email` → `--preview` → execução real.

## 5. Execução automática pelo GitHub Actions

O arquivo `.github/workflows/job-alerts.yml` agenda a execução para **9h17 de segunda a sexta-feira (America/Sao_Paulo)** e permite rodar manualmente na aba **Actions**.

No repositório, abra **Settings → Secrets and variables → Actions**.

**Secrets (dados privados):**

| Nome | Valor |
|---|---|
| `JOOBLE_API_KEY` | Chave da Jooble |
| `TELEGRAM_BOT_TOKEN` | Token do bot |
| `TELEGRAM_CHAT_ID` | ID do chat destinatário |
| `EMAIL_FROM` | Gmail que envia |
| `EMAIL_TO` | E-mail do seu pai (ou e-mails separados por `;`) |
| `EMAIL_APP_PASSWORD` | Senha de aplicativo do Gmail |

**Variables (configurações não secretas):**

`JOB_LOCATION`, `JOB_KEYWORDS`, `SEND_TELEGRAM`, `SEND_EMAIL` e, se necessário, `JOB_LOCATIONS`, `JOB_RADIUS`, `MAX_JOBS`, `MAX_QUERIES_PER_RUN`, `EXCLUDED_TITLE_TERMS`, `REQUIRED_TITLE_TERMS`, `EXCLUDED_COMPANIES`, `SMTP_HOST`, `SMTP_PORT`.

O workflow salva `data/sent_jobs.json` com um commit automático. Ele tenta salvar esse arquivo **mesmo se um dos dois canais falhar**, para não reenviar pelo canal que já deu certo. Como a branch precisa aceitar commits da Action, confira as permissões de escrita e regras de proteção do repositório. Mais adiante, podemos substituir o JSON por banco de dados.

**Segurança:** nunca adicione `.env` ao Git e nunca copie credenciais diretamente no workflow. Ele usa `secrets.*` justamente para isso.

## 6. Onde mexer no código

| Arquivo/função | Responsabilidade | Precisa alterar? |
|---|---|---|
| `.env` | Personalizações e credenciais | **Sim** |
| `get_settings()` | Lê cargos, localidades e filtros | Só para adicionar uma configuração nova |
| `search_jobs()` | Consulta a Jooble | Só se mudar a fonte/API |
| `relevant()` | Aplica filtros de cargo/empresa | Quando quiser filtros melhores |
| `job_message()` | Monta texto HTML do Telegram | Se quiser mudar a aparência |
| `send_telegram()` | Faz a chamada à API do Telegram | Normalmente não |
| `send_email()` | Monta e envia e-mail em texto e HTML | Se quiser personalizar o e-mail |
| `notification_settings()` | Liga/desliga cada destino | Normalmente não |
| `load_history()` / `save_history()` | Evita duplicações por canal | Não, por enquanto |
| `main()` | Coordena tudo | Evite mexer no MVP |
| `job-alerts.yml` | Frequência e secrets do GitHub | Sim, para mudar o horário |

## 7. Próximas evoluções possíveis

1. **Novas fontes de vagas:** criar módulos `providers/` com APIs oficiais ou autorizadas, sem depender apenas da Jooble.
2. **Matching pessoal:** complementar a especialidade com currículo, senioridade, idiomas e experiência.
3. **Múltiplos usuários:** acrescentar contas e PostgreSQL ao armazenamento SQLite da interface local.
4. **Alertas personalizáveis:** frequência diferente para e-mail (resumo diário) e Telegram (alerta de vagas urgentes).
5. **Candidaturas:** acrescentar o acompanhamento das candidaturas ao dashboard existente.

### Limitações atuais

- Só usa a primeira página dos resultados de cada busca na Jooble, para poupar requisições.
- A classificação depende dos títulos e das descrições disponibilizados pela fonte; anúncios resumidos podem omitir informações.
- O histórico por canal evita repetições normais; raramente, um serviço pode aceitar o envio e perder a conexão antes de confirmar, levando a uma repetição.
- O bot usa **uma lista de destinatários de e-mail** e **um chat do Telegram**; múltiplos perfis ficam para uma próxima versão.
- O projeto não realiza scraping de plataformas que proíbam automações não autorizadas.

---

Referências: [API Jooble](https://jooblehelpcenter.freshdesk.com/en/support/solutions/articles/60001448238-rest-api-documentation) · [Telegram Bot API](https://core.telegram.org/bots/api) · [SMTP Python](https://docs.python.org/3/library/smtplib.html) · [GitHub Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)

## Filtros de engenharia, remuneração e Gemini

O perfil inicial busca **engenharia de produto físico e engenharia de produção/manufatura**. Na interface, escolha somente Produto, somente Produção ou as duas áreas. Cargos de vendas, RH, cozinha, contabilidade, eventos, construção civil e produtos de software são descartados quando identificados pelo título ou descrição. Termos personalizados continuam disponíveis para outras buscas; o piso salarial permanece obrigatório.

O mínimo é **R$ 7.000 por mês**. A comparação usa o **menor valor publicado** de uma faixa. Remuneração anual é dividida por 12; semanal usa 52/12. Valores por hora só são comparados quando a jornada semanal está informada. Salários em outras moedas usam a cotação de referência [Frankfurter](https://frankfurter.dev/), com moeda, data e valor equivalente nos detalhes. Não estima benefícios, salário líquido, jornada ou salários ausentes. Moeda/período incerto, salário estimado, teto sem piso ou cotação indisponível ficam em **Para análise**. Essas vagas podem ser salvas; o backend impede enviá-las como alertas aprovados, inclusive se vierem de favoritos ou históricos antigos.

Os perfis usam variações de português, inglês, espanhol, alemão, francês, italiano, chinês, japonês e coreano, com gênero, plural, acentos, siglas e nomes compostos. O idioma do país tem prioridade. A busca exibe os termos consultados por fonte; os limites de requisições/páginas continuam existindo e não garantem cobertura integral. Países com outros idiomas podem usar termos personalizados e pesquisa Gemini.

Para ativar a IA, abra **Integrações → Gemini**, crie uma chave no [Google AI Studio](https://aistudio.google.com/apikey) e salve na interface local. Selecione **Gemini + Google Search** na busca. Também é possível preencher `GEMINI_API_KEY` no `.env` e reiniciar `python web.py`. A chave fica no backend. O modelo padrão é `gemini-3.1-flash-lite`, configurável por `GEMINI_MODEL`, conforme a [documentação dos modelos](https://ai.google.dev/gemini-api/docs/models).

Gemini usa [Google Search grounding](https://ai.google.dev/gemini-api/docs/generate-content/google-search) para descobrir páginas e justifica a compatibilidade de até 80 vagas. A importação exige uma fonte citada e um anúncio público `JobPosting` verificável: salários/títulos gerados pelo modelo não viram dados de vagas. Páginas sem dados estruturados continuam disponíveis nas fontes para conferência. As sugestões do Google aparecem em um iframe isolado. A integração usa a cota Google, separadamente da SerpAPI; ausência de chave ou falha da IA preserva as outras fontes e filtros.

A pesquisa Google dos modelos Gemini 3 requer acesso ao plano com faturamento, conforme a [tabela oficial de preços](https://ai.google.dev/gemini-api/docs/pricing). Uma chave pode funcionar para avaliar texto e retornar **429** ao usar Google Search. A aplicação mostra esse erro e mantém as vagas das empresas. Confira limites e faturamento no seu projeto Google; `GEMINI_SEARCH_MODEL` permite selecionar um modelo de pesquisa diferente do modelo de classificação, se disponível na sua conta.

O cadastro Jooble agora lista somente os **66 mercados divulgados**, com links de solicitação e indicadores das chaves já cadastradas. Veja o [guia completo com todos os países e formulários](docs/jooble-keys.md). A lista de países da busca geral continua abrangendo todos os países ISO para empresas e outras fontes.

O bot `python main.py` usa os mesmos critérios de área e salário, com `JOB_PROFILE=both` e `MIN_SALARY_BRL=7000`. Amplia os cargos dentro de `MAX_QUERIES_PER_RUN`, mantendo as localidades configuradas. `--preview` mostra vagas para análise sem enviar nem gravar. Em uma execução normal, grava as pendências em `data/salary_review.json`; somente vagas com salário compatível são enviadas. A pesquisa e classificação Gemini estão na interface web, onde os resultados aprovados podem ser enviados aos canais existentes.
