# Contas e configuração inicial

A primeira conta recebe o papel de administradora e herda os dados anteriores da instalação. Contas seguintes têm empresas, resultados, favoritos, contatos e preferências próprios. Senhas ficam como hashes scrypt; sessões são revogáveis e os formulários usam proteção CSRF.

Em **Primeiros passos**, cada pessoa encontra o checklist de e-mail, Telegram e preferências. O tour de dez etapas aparece no primeiro acesso, pode ser pausado, retomado e revisto; progresso pertence à conta e persiste no banco.

O e-mail de login é diferente do destinatário de alertas. O serviço Gmail SMTP e o bot Telegram são compartilhados e configurados pela administração; cada pessoa informa seu e-mail de alertas e chat ID em Primeiros passos ou Meu perfil. O vínculo Telegram usa um link pessoal de dez minutos e confirma somente mensagens privadas com o identificador correspondente. Também é possível informar o chat ID numérico manualmente.

Salve seus filtros para a automação usar seus cargos, região, país, estado, cidade e piso salarial. Termos personalizados permitem outros ramos profissionais. Gemini é opcional.

Com DATABASE_URL, a interface e o Actions usam o Neon. Sem essa variável, a interface usa SQLite local e suas alterações não aparecem na automação. O Actions não disponibiliza uma página pública de login; abrir INICIAR.cmd continua sendo necessário para acessar a interface local.

Chaves compartilhadas são privadas e acessíveis somente à administração. Alterações na interface ligada ao Neon ficam no banco; as Secrets do Actions prevalecem na automação, então atualize também as Secrets correspondentes. HUNTER_ALLOW_REGISTRATION=false no .env fecha novos cadastros; não bloqueia contas existentes. HUNTER_SETUP_TOKEN é opcional para proteger a criação da primeira conta numa instalação nova.
