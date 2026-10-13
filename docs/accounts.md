# Contas e configuração inicial

A primeira conta recebe o papel de administradora e herda os dados anteriores da instalação. Contas seguintes têm empresas, resultados, favoritos, contatos e preferências próprios. Senhas ficam como hashes scrypt; sessões são revogáveis e os formulários usam proteção CSRF.

Em **Primeiros passos**, cada pessoa encontra o checklist de e-mail, Telegram e preferências. O tour de dez etapas aparece no primeiro acesso como dicas ao lado dos controles, sem modal, desfoque ou bloqueio da página. Pode ser pausado com Esc ou pelo botão, retomado e revisto; progresso pertence à conta e persiste no banco. Em telas pequenas, a explicação pode rolar dentro da dica para manter os controles visíveis.

**Histórico → Por busca** mostra as vinte buscas mais recentes, contagens e até três prévias por pesquisa. **Ver todas as vagas desta busca** expande o resultado salvo completo. **Abrir na busca** retoma o resultado em Explorar; **Usar filtros** prepara outra consulta sem executá-la.

**Histórico → Todas as vagas** mostra o índice privado de oportunidades de todas as suas buscas, inclusive as anteriores às vinte recentes, sem repetir anúncios já deduplicados. Há páginas de quarenta vagas e filtro de salário aprovado ou para análise. É possível abrir detalhes e salvar uma oportunidade diretamente. Abrir histórico e catálogo não consulta fornecedores nem gasta cotas. Confira a disponibilidade no anúncio original: o acervo pode incluir vagas encerradas. As prévias mantêm os dados de cada busca; o catálogo usa os últimos dados disponíveis para cada anúncio.

O e-mail de login é diferente do destinatário de alertas. O serviço Gmail SMTP e o bot Telegram são compartilhados e configurados pela administração; cada pessoa informa seu e-mail de alertas e chat ID em Primeiros passos ou Meu perfil. O vínculo Telegram usa um link pessoal de dez minutos e confirma somente mensagens privadas com o identificador correspondente. Também é possível informar o chat ID numérico manualmente.

Salve seus filtros para a automação usar seus cargos, região, país, estado, cidade e piso salarial. Termos personalizados permitem outros ramos profissionais. Gemini é opcional.

Com DATABASE_URL, a interface e o Actions usam o Neon. A interface pública fica no Vercel e pode ser compartilhada pelo domínio de produção; o Actions executa a automação. Sem essa variável, o desenvolvimento local usa SQLite e suas alterações não aparecem na automação. INICIAR.cmd é apenas a alternativa local. [Publicação](vercel.md).

Chaves compartilhadas são privadas e acessíveis somente à administração. Alterações na interface ligada ao Neon ficam no banco; as Secrets do Actions prevalecem na automação, então atualize também as Secrets correspondentes. HUNTER_ALLOW_REGISTRATION=false no .env fecha novos cadastros; não bloqueia contas existentes. HUNTER_SETUP_TOKEN é opcional para proteger a criação da primeira conta numa instalação nova.
