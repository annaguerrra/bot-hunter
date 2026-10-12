# Interface pública no Vercel Hobby

O Vercel hospeda login, primeiros passos, filtros, empresas, histórico e favoritos. O Neon preserva os dados entre funções e o GitHub Actions executa os alertas de segunda a sexta-feira às 9h17 de Brasília. Nada depende do computador ligado. Use o Hobby pessoal, não comercial, e acompanhe os limites gratuitos; não ative planos pagos para este projeto. [Documentação Hobby](https://vercel.com/docs/plans/hobby).

## Publicar o repositório já importado

1. Abra **Go to Project → Settings → Environment Variables**.
2. Em **Key**, informe `DATABASE_URL`; em **Value**, cole sua conexão Neon. Para obtê-la, abra o Neon e clique **Connect → Connection string**. Exemplo fictício: `postgresql://usuario:SENHA_FICTICIA@host.example.invalid/neondb?sslmode=require`.
3. Selecione **Production**, marque Sensitive quando disponível e clique **Save**. Não precisa cadastrar Preview para publicar a produção. Se decidir usar previews, evite conectar código de branches não revisadas ao banco real.
4. Em **Build and Deployment**, mantenha **Framework Preset: Flask**, **Root Directory: ./**, sem substituir Build Command ou Output Directory. A configuração no repositório copia os recursos públicos para a CDN.
5. Em **Deployments**, escolha a versão atual da branch `main` e clique **Redeploy**, ou aguarde o deploy automático do novo commit. Um deploy antigo continua com o código antigo mesmo após alterar variáveis.
6. Abra o domínio de produção mostrado no projeto. `/health` deve retornar `{"status":"ok"}`; a página principal apresenta login. Use sua conta existente do Neon; novas contas têm preferências, contatos e resultados próprios.

O erro **Found main.py but it does not define a top-level Flask app** ocorre ao tentar hospedar o executável do bot. O `pyproject.toml` define `entrypoint = "app:app"`. A entrada `app.py` inicializa `create_app()` e exige PostgreSQL; não cria um banco temporário no Vercel. [Configuração oficial Flask](https://vercel.com/docs/frameworks/backend/flask).

Para familiares acessarem, confira **Settings → Deployment Protection**. A URL de produção deve permitir acesso sem conta Vercel; login do Bot Hunter continua obrigatório. Compartilhe o domínio de produção, não o endereço de um preview protegido.

## Variáveis no Vercel

| Nome | Valor / padrão | Necessidade |
|---|---|---|
| `DATABASE_URL` | Conexão privada Neon, exemplo fictício acima | Obrigatória em Production |
| `GEMINI_ENABLED` | `false` | Opcional; `true` habilita IA quando a chave privada existe |
| `HUNTER_ALLOW_REGISTRATION` | `true` | Opcional; `false` fecha novos cadastros |
| `HUNTER_TRUSTED_HOSTS` | `hunter.example.invalid` | Apenas para domínio próprio; domínios Vercel do projeto são reconhecidos automaticamente |
| `HUNTER_SETUP_TOKEN` | Código privado fictício `CODIGO_INSTALACAO_FICTICIO` | Apenas para criar a primeira administradora em um banco vazio; dispensável com contas migradas |
| `HUNTER_SERVERLESS` | `true` | Definida por `app.py`; mantenha ativa |
| `HUNTER_HTTPS` | `true` | Definida por `app.py`; protege o cookie de sessão |
| `EMAIL_DELIVERY_MODE` | `queue` | Definida por `app.py`; Gmail é enviado pelo Actions |
| `GEMINI_MODEL`, `GEMINI_SEARCH_MODEL` | Modelo do README, segundo vazio | Opcionais; configuração cadastrada no Neon prevalece |
| `SERPAPI_DAILY_LIMIT`, `SERPAPI_MONTHLY_LIMIT` | `3`, `250` | Opcionais; limites administrativos no Neon prevalecem |
| `WEB_MAX_MARKET_QUERIES` | `6` | Opcional; limite Jooble por busca |

Não importe todo o `.env.example` no Vercel: seus padrões de desenvolvimento desativam HTTPS e o modo serverless. `VERCEL`, `VERCEL_URL` e `VERCEL_PROJECT_PRODUCTION_URL` são variáveis de sistema da plataforma, não valores a preencher manualmente. [Variáveis de sistema](https://vercel.com/docs/environment-variables/system-environment-variables).

As chaves Jooble, SerpAPI, Gemini, token Telegram e credenciais Gmail já cadastradas ficam privadas no Neon. Para uma instalação nova, a administração cadastra as integrações no painel ou fornece as Secrets listadas no README como variáveis privadas. O Actions continua recebendo as GitHub Secrets; não remova nenhuma delas. Alterações feitas pelo painel precisam ser refletidas também nas Secrets usadas pelo Actions.

Não é necessário cadastrar `VERCEL_TOKEN`, IDs de organização ou Secrets extras no GitHub para o deploy pela integração Git já importada. Commits na branch de produção disparam novos deploys. O workflow de testes valida o código; acompanhe seu resultado antes de compartilhar a nova versão.

## Buscas, notificações e cotas

- A busca termina dentro da requisição pública e grava no Neon antes de responder. Há prazo interno de 240 segundos e limite de função de 300 segundos. Prefira país/cidade ou menos fontes por busca extensa. Resultados de fontes concluídas são preservados quando o prazo interno termina; interrupções forçadas podem impedir a gravação. [Limites de funções](https://vercel.com/docs/functions/limitations).
- O painel divide Telegram em lotes de uma vaga, com espaçamento. Cada confirmação é registrada; se houver falha, reenvie a seleção para retomar sem repetir os envios confirmados. Mantenha a página aberta durante o envio. Um envio aceito pelo Telegram cuja resposta se perdeu pode ter resultado incerto: confira o chat antes de tentar novamente.
- Gmail usa fila no Neon. O envio ocorre no Actions agendado ou por **Run workflow**, com `search` desmarcado se quiser apenas enviar pendências. O perfil mostra falhas e tentativas disponíveis.
- Limites Jooble e SerpAPI são compartilhados entre o site e o Actions. Reiniciar funções ou publicar outra versão não renova cotas. Ao acabar, o painel oferece histórico, favoritos, links de empresas, sugestões Google e LinkedIn sem chamar essas APIs. Consultas idênticas podem usar cache válido sem nova chamada.
- Gemini permanece opcional. Quando habilitado, busca com Google, verifica anúncios e auxilia a priorização. A cota Jooble não limita Gemini: são serviços independentes. Não há contador interno diário próprio para Gemini nesta versão; mantenha desligado se quiser evitar seu consumo. Erros ou limite do provedor deixam as outras fontes disponíveis, e o painel não habilita IA sozinho.

Arquivos privados `.env`, bancos, backups e logs são excluídos do upload e do pacote. `scripts/build_vercel.py` copia somente `static/` e `assets/`. Sessões, senhas protegidas, favoritos, chaves e consumo ficam no Neon; o diretório temporário da função não é usado como persistência.
