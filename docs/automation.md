# Automação com GitHub Actions e Neon

O bot roda em um runner temporário do GitHub e encerra ao concluir. O Neon guarda o estado entre execuções. A interface roda localmente e acessa o mesmo Neon quando DATABASE_URL está no .env privado. Não há servidor público permanente.

1. Mantenha o código na branch main e habilite Actions no repositório.
2. Crie um banco no plano gratuito Neon e copie a conexão PostgreSQL com SSL para a Secret DATABASE_URL.
3. Cadastre as Secrets e Variables descritas no README.
4. Cadastre o destinatário de e-mail, chat ID e preferências em cada conta na interface ligada ao Neon.
5. Execute Actions → Buscar vagas e enviar fila Gmail → Run workflow. Desmarque search para processar somente e-mails pendentes.
6. O próximo agendamento ocorre num dia útil às 9h17 de Brasília. O GitHub pode atrasar esse início.

Gmail usa SMTP SSL, porta 465, e senha de aplicativo. Cada pessoa precisa iniciar uma conversa com o bot Telegram para receber mensagens. Gemini fica desligado até GEMINI_ENABLED=true; não é requisito para enviar alertas.

## Copiar uma instalação SQLite existente

Faça isso **uma única vez**, para um banco Neon vazio, com a interface parada durante a cópia:

```powershell
python scripts/migrate_cloud.py
```

A conexão é solicitada sem exibir sua senha. O script abre SQLite somente para leitura, preserva o original, copia contas com hashes de senha, contatos, chaves, empresas, histórico e contadores e recusa um destino que já tenha contas. Sessões não são copiadas: faça login novamente.

Depois preencha DATABASE_URL no .env privado da interface e nos GitHub Secrets. Não execute novamente a migração sobre um banco já usado. Mantenha um backup do SQLite original fora do Git.

## Falhas e operação

A fila de e-mail só confirma entrega depois de o SMTP aceitar o envio. Falhas ficam em Meu perfil. Um envio interrompido vira incerto após expirar sua reserva; confira seu Gmail antes de autorizar nova tentativa. Não há reenvio automático de lotes incertos. Solicitar novamente não dispara imediatamente o workflow: rode manualmente ou aguarde o próximo agendamento.

429 e indisponibilidade de uma fonte deixam notas no histórico; as outras fontes continuam. Cotas persistem no Neon e não reiniciam a cada runner. E-mails e Telegram têm históricos separados por usuário/canal. Alterações de Secrets e Variables não alteram mensagens já enviadas.

CLOUD_ALERTS_ENABLED=false desativa as execuções do bot, inclusive manuais. Os testes de checks.yml continuam funcionando com banco temporário e valores fictícios.

Os logs públicos não exibem credenciais, contatos ou anúncios privados. Consulte o histórico autenticado para detalhes das fontes. As limitações do plano gratuito, períodos de inatividade e consumo externo devem ser acompanhados nas contas GitHub, Neon e SerpAPI.
