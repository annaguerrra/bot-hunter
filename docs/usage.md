# Uso diário e exploração sem consumir a cota

Jooble: padrão de 12 consultas por usuário/dia, 36 no conjunto da aplicação e 6 por chave/dia. A administração pode ajustar o padrão e o limite individual de cada pessoa. O dia renova à meia-noite de São Paulo. O teto estimado de 500 consultas por chave não renova diariamente: ajuste o uso anterior para refletir consultas feitas antes do cadastro ou fora da aplicação.

Cada tentativa real conta, inclusive erros. Busca idêntica pode reutilizar o cache de 24 horas sem nova consulta. Aumentar anúncios por consulta para até 100 não aumenta o número de chamadas, mas depende do que a fonte retorna e dos filtros. Mundo/região alterna mercados elegíveis com suas próprias chaves, priorizando os menos consultados; mantém o teto de consultas por busca.

Uma resposta 429 pausa a chave. Somente uma confirmação de esgotamento pelo provedor marca seu saldo estimado como esgotado. Uma chave inválida não é tratada como 500 consultas gastas. Trocar o país de uma chave não restaura seu consumo: o contador usa uma impressão criptográfica da chave.

Google Empregos: até três chamadas compartilhadas por dia e 250 por mês civil, com contagem persistente e reserva atômica. Cache evita chamadas idênticas. Página adicional e pesquisa em outro idioma podem consumir nova chamada. Os 66 pedidos estimados consideram três chamadas em cada um de 22 dias úteis; não há promessa de 66 buscas independentes por usuário. No painel administrativo, registre consumo externo anterior deste mês. Confira o período da conta SerpAPI: o contador local não consulta o saldo real a cada busca.

Quando o limite acaba, continue pelas vagas salvas e histórico, revise seu currículo contra requisitos, visite empresas cadastradas e use os links de LinkedIn/Google gerados a partir de seus filtros. As sugestões não consultam Gemini nem Jooble. Links externos e sites de empresas têm disponibilidade própria; não importam automaticamente os resultados do LinkedIn.

Salários desconhecidos ou ambíguos ficam para análise. Nenhum salário é inventado para aprovar uma vaga. Deduplicação preserva o envio por usuário/canal e combina anúncios equivalentes entre fontes quando a identificação é inequívoca; anúncios semelhantes podem permanecer separados para evitar juntar vagas distintas.
