# Bot Hunter

Busca vagas internacionais com filtros por região, país, estado e cidade, perfis de engenharia de produto e produção, termos personalizados e piso de **R$ 7.000 mensais**. Salários em outras moedas são convertidos; salários ausentes, estimados ou ambíguos ficam separados para análise e não geram alertas.

A arquitetura atual usa **GitHub Actions para executar o bot** e **Neon PostgreSQL para persistir contas, preferências, chaves, consumo, resultados e deduplicação**. A execução automática funciona com o computador desligado. A interface de configuração e consulta continua local: o Actions executa tarefas, não hospeda um site.

## Abrir a interface

No Windows, clique duas vezes em **INICIAR.cmd**, ou execute:

```powershell
.\INICIAR.cmd
```

O inicializador cria o ambiente Python, instala dependências e abre http://127.0.0.1:5000. Instale Python 3.12 antes do primeiro uso. Ele preserva o arquivo privado `.env`.

Copie `.env.example` para `.env` somente se ainda não houver configuração. Preencha `DATABASE_URL` com a mesma conexão Neon usada no GitHub para acessar os dados compartilhados. Sem essa variável, a interface usa SQLite local. Nunca publique o arquivo `.env`, o banco ou backups.

A primeira conta é administradora. Contas seguintes têm contatos, preferências, empresas, histórico e favoritos próprios. **Primeiros passos** apresenta um tour de 10 etapas, permite pausar e retomar e orienta e-mail, Telegram e filtros. O pai pode registrar seu próprio e-mail e vincular o Telegram pelo link pessoal do bot, ou informar o chat ID manualmente. Cada destinatário precisa iniciar uma conversa com o bot.

## Automação no GitHub

O workflow [job-alerts.yml](.github/workflows/job-alerts.yml) executa **de segunda a sexta-feira, às 9h17 de Brasília**, com `timezone: America/Sao_Paulo`. O GitHub pode atrasar o início; o horário não é uma garantia de execução no minuto exato. [Documentação de agendamentos](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

No repositório, abra **Actions → Buscar vagas e enviar fila Gmail → Run workflow**:

- `search=true`: consulta fontes, grava resultados e envia novidades aprovadas para os contatos de cada conta.
- `search=false`: processa somente a fila de e-mails pendentes, sem pesquisar vagas.

A automação usa preferências salvas de cada usuário; Variables de cargos e localização servem como padrão para contas sem preferências. Contas sem destinos de alerta são ignoradas. Gemini é opcional e fica desligado por padrão.

A fila Gmail persiste no Neon. Uma vaga confirmada como enviada não é reenviada ao mesmo usuário/canal. Falhas ficam visíveis em **Meu perfil** para nova tentativa explícita. Um envio interrompido de resultado incerto não é repetido automaticamente. Após solicitar uma tentativa no perfil, execute o workflow manualmente ou aguarde o próximo dia útil. O Telegram mantém histórico separado por canal e espaça os lotes.

## Secrets e Variables

Cadastre em **Settings → Secrets and variables → Actions**. Os exemplos abaixo são fictícios. Secrets não vão em Variables nem no código.

| Secret | Uso / exemplo fictício |
|---|---|
| `DATABASE_URL` | Obrigatória: `postgresql://usuario:SENHA_FICTICIA@host.example.invalid/neondb?sslmode=require` |
| `JOOBLE_API_KEY` | Chave principal brasileira: `CHAVE_JOOBLE_FICTICIA` |
| `JOOBLE_KEYS_JSON` | Regionais: `{"DE":"CHAVE_ALEMA_FICTICIA","NO":"CHAVE_NORUEGUESA_FICTICIA"}` |
| `SERPAPI_API_KEY` | Google Jobs: `CHAVE_SERPAPI_FICTICIA` |
| `TELEGRAM_BOT_TOKEN` | Bot: `123456789:TOKEN_FICTICIO` |
| `EMAIL_FROM` | Gmail remetente: `remetente@example.com` |
| `EMAIL_APP_PASSWORD` | Senha de aplicativo Gmail: `SENHA_FICTICIA_16` |
| `GEMINI_API_KEY` | Opcional; só usada com Gemini habilitado |

E-mail destinatário e chat ID pertencem ao perfil de cada conta no Neon; não precisam de Secrets separadas no workflow.

| Variable | Padrão | Finalidade |
|---|---|---|
| `CLOUD_ALERTS_ENABLED` | `true` | `false` suspende o workflow |
| `SEND_EMAIL`, `SEND_TELEGRAM` | `true` | Ativa os canais |
| `SMTP_HOST`, `SMTP_PORT` | `smtp.gmail.com`, `465` | Gmail SMTP SSL |
| `SERPAPI_DAILY_LIMIT` | `3` | Teto global diário Google Jobs |
| `SERPAPI_MONTHLY_LIMIT` | `250` | Teto global mensal Google Jobs |
| `GEMINI_ENABLED` | `false` | IA opcional |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | Modelo para IA |
| `GEMINI_SEARCH_MODEL` | vazio | Modelo de pesquisa; vazio usa o anterior |
| `JOB_KEYWORDS` | `product engineer;production engineer;engenheiro de produto` | Até três termos padrão |
| `JOB_PROFILE` | `both` | `product`, `production`, `both` ou `custom` |
| `MIN_SALARY_BRL` | `7000` | Piso mensal em reais |
| `JOB_COUNTRY` | `BR` | País ISO padrão |
| `JOB_LOCATION` | vazio | Cidade padrão |
| `MAX_JOBS` | `100` | Máximo de vagas aprovadas por pessoa/execução |
| `WEB_MAX_MARKET_QUERIES` | `6` | Teto de consultas Jooble por busca |

Limites alterados pela administração no painel ficam no Neon e têm prioridade sobre os padrões SerpAPI do ambiente. As Secrets do Actions têm prioridade sobre as credenciais compartilhadas no banco: se mudar uma chave pelo painel, atualize também a Secret correspondente. Não altere os padrões de personalização esperando substituir preferências já salvas.

O script opcional `scripts/setup_github.py` usa o login Git existente e criptografa as Secrets antes de enviá-las. Requer `python -m pip install PyNaCl`. Preserva Secrets existentes, exceto a SerpAPI fornecida para configuração; nunca exibe os valores. `DATABASE_URL` é cadastrada manualmente no GitHub.

## Fontes e consumo

- **Jooble**: chave por país, enviada somente ao endpoint correspondente. Obtenha no site regional, por exemplo [Brasil](https://br.jooble.org/api/about) ou [Noruega](https://no.jooble.org/api/about). Países já configurados saem do seletor de cadastro.
- **Google Empregos**: segunda fonte via SerpAPI, mecanismo `google_jobs`. [Obter chave](https://serpapi.com/manage-api-key). Normaliza anúncios junto à Jooble; deduplicação persiste no Neon por usuário e canal.
- **Empresas**: Bosch, Continental/ContiTech, BEUMER Group, Renesas Electronics e Sika no catálogo. Cadastre páginas SmartRecruiters, Greenhouse, Lever ou páginas públicas com anúncios estruturados. [Empresas verificadas](docs/verified-companies.md).
- **Gemini opcional**: auxilia pesquisa com Google e descoberta de empresas e priorização de anúncios verificados. Não inventa salário para aprovar vagas. Sem chave ou quando desligado, Jooble, SerpAPI e empresas seguem disponíveis.

Cotas Jooble padrão: **12 por usuário/dia, 36 compartilhadas/dia e 6 por chave/dia**, com estimativa conservadora de 500 consultas totais por chave. O consumo anterior ao cadastro precisa ser informado pela administração; 500 é o limite de proteção da aplicação, não uma consulta ao saldo real do provedor. Cache de 24 horas evita repetir chamadas idênticas. Mundo/região usa rotação dos mercados configurados dentro do teto por busca.

SerpAPI: **até 3 novas consultas por dia e 250 por mês**, compartilhadas entre painel e automação, incluindo paginação, tentativas com erro e respostas vazias. Três consultas em 22 dias úteis equivalem a aproximadamente 66 consultas, deixando margem. O contador usa mês civil de São Paulo: confira o ciclo e consumo da conta no provedor e registre uso externo no painel. [Plano gratuito SerpAPI](https://serpapi.com/pricing).

Quando a cota acaba, **Explorar sem Jooble** oferece histórico, favoritos, sites de empresas e links de pesquisa no Google e LinkedIn sem consumir a API Jooble. Resultados podem encerrar: confira o anúncio original. Termos em outros idiomas ampliam a busca, mas nenhuma fonte garante todas as vagas do mundo. [Detalhes de uso](docs/usage.md).

## Comandos e testes

```powershell
python web.py
python main.py --preview
python main.py --chat-id
python main.py --test-telegram
python main.py --test-email
python main.py
python -m unittest discover -s tests -v
node --check static/app.js
node --check static/onboarding.js
```

Os comandos `--test-telegram`, `--test-email` e execução completa enviam mensagens reais para os destinos da CLI no `.env`. O preview não envia alertas. A automação multiusuário usa `python scripts/cloud_alerts.py --search`, não o histórico local da CLI.

O workflow [checks.yml](.github/workflows/checks.yml) testa sem Secrets de produção, valida JavaScript e verifica migração, isolamento, cotas e deduplicação em PostgreSQL descartável. [Configuração da automação e migração](docs/automation.md), [contas e acesso](docs/accounts.md).

Para manter o projeto gratuito, use os planos gratuitos e não habilite faturamento adicional. GitHub Actions não exige hospedagem web: em repositório privado, confira os minutos incluídos na conta; no público, os runners padrão são gratuitos. [Cobrança Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
