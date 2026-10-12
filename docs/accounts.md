# Contas e preferências pessoais

Abra http://127.0.0.1:5000 e crie sua conta com nome, e-mail e senha de pelo menos 12 caracteres. A **primeira conta é administradora** e recebe o histórico, favoritos, empresas e registros de envio da instalação anterior. As chaves de pesquisa existentes continuam no `.env`; a migração de contas não as altera.

Antes de migrar um banco antigo, a aplicação cria `data/hunter.sqlite.before-users.bak` usando a API de backup do SQLite. Banco, backup, chaves de sessão e credenciais ficam fora do Git. Preserve esses arquivos ao mover a aplicação para outro computador.

## Cada pessoa tem seu radar

- Histórico, resultados, favoritos, empresas ativas e registros de envio são separados por usuário. Identificadores de outra conta não dão acesso aos seus dados.
- Em **Explorar vagas**, escolha perfil, cargos, destinos, fontes e salário. Em **Meu perfil**, clique em **Salvar filtros atuais como meu padrão**; eles serão restaurados na próxima visita.
- Para outros ramos, escolha **Perfil personalizado** e informe até três cargos ou sinônimos separados por `;`. O filtro de título pode ser ampliado. O mínimo salarial é próprio desses filtros; perfis de engenharia mantêm o piso de R$ 7.000 mensais.
- Em **Meu perfil**, cadastre o e-mail de alertas e o chat ID do seu Telegram. Novas contas não herdam os destinatários da administradora. O envio exige seleção explícita de vagas com salário confirmado.
- Em **Empresas**, pause, remova ou cadastre páginas de carreira; essas escolhas afetam somente sua conta. **Descobrir empresas** usa seus filtros e verifica anúncios públicos antes de sugerir o cadastro.

## Administração e sessões

Somente a administradora pode alterar Gemini, SerpAPI e as chaves regionais Jooble compartilhadas. O transporte de Telegram e SMTP continua configurado no `.env`, enquanto os destinatários são pessoais. As chaves não são devolvidas pela API nem enviadas nos prompts Gemini.

As senhas usam hash `scrypt`. Sessões são assinadas, duram até sete dias e têm revogação no banco; sair revoga a sessão, e trocar a senha encerra as outras sessões da mesma pessoa. Cookies usam `HttpOnly` e `SameSite=Lax`. As alterações exigem um token CSRF associado à sessão e passam pela verificação de origem. Há limites persistentes de tentativas de login, cadastro e consultas. [Segurança no Flask](https://flask.palletsprojects.com/en/stable/web-security/), [hash de senhas no Werkzeug](https://werkzeug.palletsprojects.com/en/stable/utils/#werkzeug.security.generate_password_hash).

## Preparar uma instalação pública

Esta implementação adiciona a base multiusuário à aplicação local. O comando `python web.py` continua limitado a `127.0.0.1`; ele não publica a aplicação.

Para hospedagem, use servidor WSGI, HTTPS e proxy configurado pelo responsável pela infraestrutura. Defina `HUNTER_HTTPS=true` e `HUNTER_TRUSTED_HOSTS` com os domínios reais. Para controlar novos cadastros, use `HUNTER_ALLOW_REGISTRATION=false` depois de criar a administradora. Se a primeira conta precisar ser criada remotamente, configure `HUNTER_SETUP_TOKEN` com um segredo forte; informe-o somente na instalação inicial. Ele também será exigido localmente quando estiver configurado.

O banco atual é SQLite e as buscas são executadas por threads no processo web. Use uma única instância nesse estágio. Distribuição entre servidores, fila durável de trabalhos, verificação de e-mail e recuperação de senha por e-mail ainda dependem de implementação antes de uma operação pública maior. A CLI continua sendo a automação local da instalação, independente das contas web.

## Conferência da interface

`scripts/check_accounts_ui.py` usa duas contas fictícias e deve apontar para uma instância temporária vazia numa porta diferente de 5000. Ele não envia alertas. Para `scripts/check_ui.py`, crie sua conta antes e informe `HUNTER_QA_EMAIL` e `HUNTER_QA_PASSWORD` no ambiente privado; esse script confere as integrações de uma conta administradora.
