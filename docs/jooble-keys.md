# Como solicitar e cadastrar as chaves Jooble

A lista abaixo contém os **66 mercados divulgados pela Jooble**, conferida em **12/10/2026**. Uma chave é vinculada ao domínio/país em que foi solicitada. Não há uma chave mundial. Links de solicitação usam a rota oficial `/api/about`; a aprovação e a disponibilidade da API dependem da Jooble.

Fontes: [lista regional oficial](https://jooble.org/) · [restrições, cadastro e limites da API](https://help.jooble.org/en/support/solutions/articles/60001448238-rest-api-documentation).

## Passo a passo

1. Abra a aplicação em http://127.0.0.1:5000 e entre em **Integrações → Jooble por país**.
2. Na lista de mercados, clique em **Solicitar chave** para abrir o formulário oficial daquele país.
3. Preencha nome, cargo, e-mail e telefone com seus dados reais. No campo **Website**, use o endereço público real do projeto, como https://github.com/annaguerrra/bot-hunter, se o formulário aceitar um repositório. Se exigir um site publicado, informe a URL pública da aplicação quando existir. `localhost` só funciona no seu computador.
4. Aguarde a resposta da Jooble. Não há garantia de aprovação ou prazo de entrega.
5. Volte à aplicação, clique em **Cadastrar** no mesmo país, cole a chave recebida e salve. A chave fica no `.env` privado; a lista marca o país como configurado.
6. Repita para os demais países. A chave brasileira existente já está cadastrada.

O plano gratuito informa **500 consultas por chave durante toda sua validade**, não por mês. O bot limita o número de consultas por execução. Solicitar chaves para países distintos amplia mercados; não renova a cota de um país.

## Todos os mercados

As regiões abaixo seguem o catálogo geográfico da aplicação. O nome da variável serve como alternativa ao cadastro pela interface. **GB** usa `uk.jooble.org`, **JP** usa `ja.jooble.org` e **US** usa `jooble.org`. Países fora da lista, como China continental, podem ser pesquisados por empresas e Gemini.

### Américas (14)

| País / território | Solicitar chave | Variável privada |
|---|---|---|
| Argentina (AR) | [Formulário](https://ar.jooble.org/api/about) | `JOOBLE_API_KEY_AR` |
| Brasil (BR) | [Formulário](https://br.jooble.org/api/about) | `JOOBLE_API_KEY_BR` |
| Canadá (CA) | [Formulário](https://ca.jooble.org/api/about) | `JOOBLE_API_KEY_CA` |
| Chile (CL) | [Formulário](https://cl.jooble.org/api/about) | `JOOBLE_API_KEY_CL` |
| Colômbia (CO) | [Formulário](https://co.jooble.org/api/about) | `JOOBLE_API_KEY_CO` |
| Costa Rica (CR) | [Formulário](https://cr.jooble.org/api/about) | `JOOBLE_API_KEY_CR` |
| El Salvador (SV) | [Formulário](https://sv.jooble.org/api/about) | `JOOBLE_API_KEY_SV` |
| Equador (EC) | [Formulário](https://ec.jooble.org/api/about) | `JOOBLE_API_KEY_EC` |
| Estados Unidos (US) | [Formulário](https://jooble.org/api/about) | `JOOBLE_API_KEY_US` |
| México (MX) | [Formulário](https://mx.jooble.org/api/about) | `JOOBLE_API_KEY_MX` |
| Peru (PE) | [Formulário](https://pe.jooble.org/api/about) | `JOOBLE_API_KEY_PE` |
| Porto Rico (PR) | [Formulário](https://pr.jooble.org/api/about) | `JOOBLE_API_KEY_PR` |
| República Dominicana (DO) | [Formulário](https://do.jooble.org/api/about) | `JOOBLE_API_KEY_DO` |
| Uruguai (UY) | [Formulário](https://uy.jooble.org/api/about) | `JOOBLE_API_KEY_UY` |

### Europa (26)

| País / território | Solicitar chave | Variável privada |
|---|---|---|
| Alemanha (DE) | [Formulário](https://de.jooble.org/api/about) | `JOOBLE_API_KEY_DE` |
| Bulgária (BG) | [Formulário](https://bg.jooble.org/api/about) | `JOOBLE_API_KEY_BG` |
| Bélgica (BE) | [Formulário](https://be.jooble.org/api/about) | `JOOBLE_API_KEY_BE` |
| Bósnia e Herzegovina (BA) | [Formulário](https://ba.jooble.org/api/about) | `JOOBLE_API_KEY_BA` |
| Chéquia (CZ) | [Formulário](https://cz.jooble.org/api/about) | `JOOBLE_API_KEY_CZ` |
| Croácia (HR) | [Formulário](https://hr.jooble.org/api/about) | `JOOBLE_API_KEY_HR` |
| Dinamarca (DK) | [Formulário](https://dk.jooble.org/api/about) | `JOOBLE_API_KEY_DK` |
| Eslováquia (SK) | [Formulário](https://sk.jooble.org/api/about) | `JOOBLE_API_KEY_SK` |
| Espanha (ES) | [Formulário](https://es.jooble.org/api/about) | `JOOBLE_API_KEY_ES` |
| Finlândia (FI) | [Formulário](https://fi.jooble.org/api/about) | `JOOBLE_API_KEY_FI` |
| França (FR) | [Formulário](https://fr.jooble.org/api/about) | `JOOBLE_API_KEY_FR` |
| Grécia (GR) | [Formulário](https://gr.jooble.org/api/about) | `JOOBLE_API_KEY_GR` |
| Hungria (HU) | [Formulário](https://hu.jooble.org/api/about) | `JOOBLE_API_KEY_HU` |
| Irlanda (IE) | [Formulário](https://ie.jooble.org/api/about) | `JOOBLE_API_KEY_IE` |
| Itália (IT) | [Formulário](https://it.jooble.org/api/about) | `JOOBLE_API_KEY_IT` |
| Noruega (NO) | [Formulário](https://no.jooble.org/api/about) | `JOOBLE_API_KEY_NO` |
| Países Baixos (NL) | [Formulário](https://nl.jooble.org/api/about) | `JOOBLE_API_KEY_NL` |
| Polónia (PL) | [Formulário](https://pl.jooble.org/api/about) | `JOOBLE_API_KEY_PL` |
| Portugal (PT) | [Formulário](https://pt.jooble.org/api/about) | `JOOBLE_API_KEY_PT` |
| Reino Unido (GB) | [Formulário](https://uk.jooble.org/api/about) | `JOOBLE_API_KEY_GB` |
| Roménia (RO) | [Formulário](https://ro.jooble.org/api/about) | `JOOBLE_API_KEY_RO` |
| Suécia (SE) | [Formulário](https://se.jooble.org/api/about) | `JOOBLE_API_KEY_SE` |
| Suíça (CH) | [Formulário](https://ch.jooble.org/api/about) | `JOOBLE_API_KEY_CH` |
| Sérvia (RS) | [Formulário](https://rs.jooble.org/api/about) | `JOOBLE_API_KEY_RS` |
| Ucrânia (UA) | [Formulário](https://ua.jooble.org/api/about) | `JOOBLE_API_KEY_UA` |
| Áustria (AT) | [Formulário](https://at.jooble.org/api/about) | `JOOBLE_API_KEY_AT` |

### Ásia (20)

| País / território | Solicitar chave | Variável privada |
|---|---|---|
| Arábia Saudita (SA) | [Formulário](https://sa.jooble.org/api/about) | `JOOBLE_API_KEY_SA` |
| Azerbaijão (AZ) | [Formulário](https://az.jooble.org/api/about) | `JOOBLE_API_KEY_AZ` |
| Barém (BH) | [Formulário](https://bh.jooble.org/api/about) | `JOOBLE_API_KEY_BH` |
| Catar (QA) | [Formulário](https://qa.jooble.org/api/about) | `JOOBLE_API_KEY_QA` |
| Cazaquistão (KZ) | [Formulário](https://kz.jooble.org/api/about) | `JOOBLE_API_KEY_KZ` |
| Coreia, República da (KR) | [Formulário](https://kr.jooble.org/api/about) | `JOOBLE_API_KEY_KR` |
| Emirados Árabes Unidos (AE) | [Formulário](https://ae.jooble.org/api/about) | `JOOBLE_API_KEY_AE` |
| Filipinas (PH) | [Formulário](https://ph.jooble.org/api/about) | `JOOBLE_API_KEY_PH` |
| Hong Kong (HK) | [Formulário](https://hk.jooble.org/api/about) | `JOOBLE_API_KEY_HK` |
| Indonésia (ID) | [Formulário](https://id.jooble.org/api/about) | `JOOBLE_API_KEY_ID` |
| Japão (JP) | [Formulário](https://ja.jooble.org/api/about) | `JOOBLE_API_KEY_JP` |
| Kuwait (KW) | [Formulário](https://kw.jooble.org/api/about) | `JOOBLE_API_KEY_KW` |
| Malásia (MY) | [Formulário](https://my.jooble.org/api/about) | `JOOBLE_API_KEY_MY` |
| Paquistão (PK) | [Formulário](https://pk.jooble.org/api/about) | `JOOBLE_API_KEY_PK` |
| Singapura (SG) | [Formulário](https://sg.jooble.org/api/about) | `JOOBLE_API_KEY_SG` |
| Tailândia (TH) | [Formulário](https://th.jooble.org/api/about) | `JOOBLE_API_KEY_TH` |
| Taiwan, Província da China (TW) | [Formulário](https://tw.jooble.org/api/about) | `JOOBLE_API_KEY_TW` |
| Turquia (TR) | [Formulário](https://tr.jooble.org/api/about) | `JOOBLE_API_KEY_TR` |
| Uzbequistão (UZ) | [Formulário](https://uz.jooble.org/api/about) | `JOOBLE_API_KEY_UZ` |
| Índia (IN) | [Formulário](https://in.jooble.org/api/about) | `JOOBLE_API_KEY_IN` |

### África (4)

| País / território | Solicitar chave | Variável privada |
|---|---|---|
| Egito (EG) | [Formulário](https://eg.jooble.org/api/about) | `JOOBLE_API_KEY_EG` |
| Marrocos (MA) | [Formulário](https://ma.jooble.org/api/about) | `JOOBLE_API_KEY_MA` |
| Nigéria (NG) | [Formulário](https://ng.jooble.org/api/about) | `JOOBLE_API_KEY_NG` |
| África do Sul (ZA) | [Formulário](https://za.jooble.org/api/about) | `JOOBLE_API_KEY_ZA` |

### Oceania (2)

| País / território | Solicitar chave | Variável privada |
|---|---|---|
| Austrália (AU) | [Formulário](https://au.jooble.org/api/about) | `JOOBLE_API_KEY_AU` |
| Nova Zelândia (NZ) | [Formulário](https://nz.jooble.org/api/about) | `JOOBLE_API_KEY_NZ` |
