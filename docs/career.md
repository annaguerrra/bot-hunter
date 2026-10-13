# Central de Carreira

A Central reúne orientações curtas em português e ações práticas, com atribuição e link ao original. Não copia artigos completos nem apresenta dicas como vagas. O perfil escolhido em Explorar vagas prioriza exemplos editoriais; não representa análise do LinkedIn ou currículo real da pessoa.

Fontes conferidas na pesquisa de **12/10/2026**:

- [LinkedIn Help: perfil profissional](https://www.linkedin.com/help/linkedin/answer/a554351): especialidade, resumo, experiências e competências.
- [LinkedIn Help: alertas de vagas](https://www.linkedin.com/help/linkedin/answer/a511279): configurar alertas diretamente na plataforma.
- [LinkedIn Talent Blog: fotografia de perfil](https://www.linkedin.com/business/talent/blog/product-tips/tips-for-taking-professional-linkedin-profile-pictures): foto atual, iluminação e enquadramento.
- [Harvard: currículo](https://careerservices.fas.harvard.edu/resources/create-a-strong-resume/): linguagem clara, resultados reais e adaptação ao cargo. Convenções variam por país.
- [MIT: preparação de entrevistas](https://capd.mit.edu/resources/interview-primer/): pesquisa da empresa e preparação de exemplos STAR.
- [MIT: networking](https://capd.mit.edu/blog/2022/03/02/networking-primer-for-first-year-undergraduates/): conversas informativas, organização e acompanhamento de contatos.

O link STAR específico enviado no pacote retornou HTTP 429 na consulta. Utilizamos o Interview primer do próprio MIT, cuja pesquisa oficial confirma a orientação STAR. Alguns sites limitam consultas automatizadas; isso não determina a disponibilidade ao abrir o original no navegador.

## Uso

1. Abra **Central de Carreira** e escolha LinkedIn/imagem, currículo, entrevistas ou networking/planejamento.
2. Pesquise palavras como foto, resultados ou STAR e escolha uma ação para realizar.
3. Marque o checklist manual do LinkedIn e escreva uma experiência real nos campos Situação, Tarefa, Ação e Resultado.
4. Clique **Salvar meu progresso e rascunho**. Ao voltar, sua própria conta recupera o conteúdo; filtros não sobrescrevem rascunhos não salvos.

Nenhum perfil LinkedIn é acessado ou rastreado. Os links de vagas abrem pesquisas manuais; alertas LinkedIn são configurados no próprio serviço. Não há login, candidatura ou mensagens automáticas no LinkedIn. O rascunho fica no SQLite/Neon privado e não é enviado ao Gemini. A Central requer acesso à aplicação; não é um modo offline do navegador. Na instalação local, seus conteúdos e exercícios funcionam sem consultar fontes externas.

## Atualização editorial

`resources/career_resources.json` é um catálogo curado, não um feed de notícias. Para acrescentar ou revisar dicas, confira o conteúdo no site oficial, escreva um resumo original, informe título, categoria, ação, fonte, idioma e data de verificação. Atualizações entram pelo deploy normal, sem cron extra ou chamadas de API ao abrir a página. Novas instituições precisam entrar na lista permitida em `jobhunter/career_resources.py` após revisão.

`resources/companies.json` segue a mesma separação entre sugestões públicas e cadastros privados. Esses JSONs são versionados; chaves, senhas, contatos e rascunhos nunca entram neles.

## Validação

```powershell
python -m unittest discover -s tests -v
python -m compileall -q jobhunter web.py main.py
node --check static/app.js
node --check static/development.js
node --check static/onboarding.js
node tests/check_notifications.cjs
git diff --check
```

Os testes unitários utilizam mocks e contas fictícias, sem consultas reais às fontes de vagas. O contrato PostgreSQL é opcional, usando `HUNTER_TEST_DATABASE_URL` com um banco de testes ou schema isolado validado; não modifique o schema de produção para testar.
