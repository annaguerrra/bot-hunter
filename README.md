# Job Hunter Bot — Engenharia de Produção

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
| `MAX_JOBS` | Vagas novas por canal por execução (1 a 15) | `8` |
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
2. **Matching por perfil:** priorizar vagas por senioridade, áreas, cidade e experiência do seu pai.
3. **Banco de dados:** migrar histórico e vagas para SQLite/PostgreSQL quando passar a ter múltiplas fontes ou usuários.
4. **Alertas personalizáveis:** frequência diferente para e-mail (resumo diário) e Telegram (alerta de vagas urgentes).
5. **Dashboard:** permitir visualizar vagas, marcar candidaturas e consultar histórico.

### Limitações atuais

- Só usa a primeira página dos resultados de cada busca na Jooble, para poupar requisições.
- Os filtros são por título e empresa, não analisam a descrição completa.
- O histórico por canal evita repetições normais; raramente, um serviço pode aceitar o envio e perder a conexão antes de confirmar, levando a uma repetição.
- O bot usa **uma lista de destinatários de e-mail** e **um chat do Telegram**; múltiplos perfis ficam para uma próxima versão.
- O projeto não realiza scraping de plataformas que proíbam automações não autorizadas.

---

Referências: [API Jooble](https://jooblehelpcenter.freshdesk.com/en/support/solutions/articles/60001448238-rest-api-documentation) · [Telegram Bot API](https://core.telegram.org/bots/api) · [SMTP Python](https://docs.python.org/3/library/smtplib.html) · [GitHub Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
