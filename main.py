"""Busca vagas na Jooble e envia oportunidades novas por Telegram e e-mail.

COMO PERSONALIZAR:
    1. Copie .env.example para .env.
    2. Edite as opções do .env (cargos, cidades, filtros, credenciais).
    3. Não precisa alterar este arquivo para mudar a busca.

Este arquivo mantém o ciclo de alertas Jooble. Regras de área e salário são
compartilhadas com a interface web pelos módulos do pacote jobhunter.
"""

import argparse
import html
import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
import unicodedata
from pathlib import Path

import requests
from dotenv import load_dotenv
from jobhunter import matching, salary

# Lê automaticamente as variáveis do arquivo .env, caso ele exista.
# Variáveis do ambiente (como os Secrets do GitHub) também funcionam.
load_dotenv()

# ========== CAMINHOS E ENDPOINTS ==========
# Normalmente você NÃO precisa alterar nada nesta seção.
BASE_DIR = Path(__file__).resolve().parent
HISTORY_FILE = BASE_DIR / "data" / "sent_jobs.json"  # IDs das vagas já enviadas
API_URL = "https://br.jooble.org/api/{}"  # API da Jooble brasileira
TELEGRAM_URL = "https://api.telegram.org/bot{}/{}"  # API oficial do Telegram


# ========== CONFIGURAÇÕES ==========
def required_env(name):
    """Lê uma configuração obrigatória; avisa se você esqueceu de preenchê-la."""
    value = os.getenv(name, "").strip()
    if not value or value.startswith("COLE_"):
        raise RuntimeError(f"Configure {name} no .env ou nas variáveis de ambiente.")
    return value


def split_terms(value):
    """Transforma 'termo 1;termo 2' em uma lista com dois termos."""
    return [part.strip() for part in value.split(";") if part.strip()]


def get_settings():
    """Agrupa os filtros configurados no .env (não há necessidade de editar o Python)."""
    # CARGOS: cada palavra-chave gera uma consulta para cada cidade.
    keywords = split_terms(os.getenv(
        "JOB_KEYWORDS", "engenheiro de produto;engenheiro de produção"
    ))

    # CIDADES: use JOB_LOCATIONS para várias, ou JOB_LOCATION para apenas uma.
    # Exemplo de múltiplas cidades: JOB_LOCATIONS=Curitiba;Ponta Grossa
    location_text = os.getenv("JOB_LOCATIONS", "").strip() or os.getenv("JOB_LOCATION", "").strip()
    locations = split_terms(location_text)

    # FILTROS: são aplicados DEPOIS da API retornar as vagas.
    # "REQUIRED_TITLE_TERMS" é opcional: se vazio, não bloqueia nenhum título.
    # Se preenchido, basta o título conter UM dos termos para passar.
    required_titles = split_terms(os.getenv("REQUIRED_TITLE_TERMS", ""))
    excluded_titles = split_terms(os.getenv(
        "EXCLUDED_TITLE_TERMS", "estágio;estagiário;aprendiz"
    ))
    excluded_companies = split_terms(os.getenv("EXCLUDED_COMPANIES", ""))

    # LIMITES: MAX_JOBS controla quantas vagas vão na mensagem.
    # MAX_QUERIES_PER_RUN impede consumir a cota da API sem perceber.
    try:
        max_jobs = max(1, min(int(os.getenv("MAX_JOBS", "8")), 15))
        max_queries = int(os.getenv("MAX_QUERIES_PER_RUN", "4"))
    except ValueError:
        raise ValueError("MAX_JOBS e MAX_QUERIES_PER_RUN precisam ser números inteiros.") from None

    radius = os.getenv("JOB_RADIUS", "80").strip()

    if not keywords:
        raise ValueError("Configure pelo menos um cargo em JOB_KEYWORDS.")
    if not locations:
        raise ValueError("Configure JOB_LOCATION ou JOB_LOCATIONS no .env.")
    if radius not in {"0", "4", "8", "16", "26", "40", "80"}:
        raise ValueError("JOB_RADIUS deve ser 0, 4, 8, 16, 26, 40 ou 80 (km).")
    if max_queries < 1:
        raise ValueError("MAX_QUERIES_PER_RUN deve ser maior que zero.")
    profile = os.getenv("JOB_PROFILE", "both").strip()
    if profile not in {"product", "production", "both", "custom"}:
        raise ValueError("JOB_PROFILE deve ser product, production, both ou custom.")
    try:
        salary_min = float(os.getenv("MIN_SALARY_BRL", "7000"))
    except ValueError:
        raise ValueError("MIN_SALARY_BRL precisa ser um número.") from None
    if not 7000 <= salary_min <= 1000000:
        raise ValueError("MIN_SALARY_BRL deve ser pelo menos 7000 por mês.")

    return {
        "keywords": keywords,
        "locations": locations,
        "required_titles": required_titles,
        "excluded_titles": excluded_titles,
        "excluded_companies": excluded_companies,
        "max_jobs": max_jobs,
        "max_queries": max_queries,
        "radius": radius,
        "profile": profile, "salary_min": salary_min,
    }


def search_count(settings):
    """Uma consulta por combinação de cargo + cidade."""
    return len(settings["keywords"]) * len(settings["locations"])


def show_plan(settings):
    """Exibe quantas consultas serão feitas SEM acessar nenhuma API."""
    settings = {**settings, "keywords": effective_keywords(settings)}
    count = search_count(settings)
    print("Cargos:", ", ".join(settings["keywords"]))
    print("Cidades:", ", ".join(settings["locations"]))
    print("Raio:", settings["radius"], "km")
    print(f"Perfil: {settings['profile']} · mínimo mensal: R$ {settings['salary_min']:,.0f}")
    print(f"Consultas previstas por execução: {count} (limite configurado: {settings['max_queries']})")
    if count > settings["max_queries"]:
        print("ATENÇÃO: aumente MAX_QUERIES_PER_RUN ou reduza cargos/cidades.")
    print("Este comando não consulta a Jooble e não consome requisições.")


def effective_keywords(settings):
    if settings["profile"] == "custom" or search_count(settings) > settings["max_queries"]:
        return settings["keywords"]
    return matching.expand_queries(settings["keywords"], settings["profile"], "BR",
                                   limit=max(1, settings["max_queries"] // len(settings["locations"])))


# ========== HISTÓRICO E FILTROS ==========
def normalize(value):
    """Remove acentos e pontuação para comparar textos sem depender da escrita exata."""
    # Assim, "produção" e "producao" são entendidos como a mesma palavra.
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def load_history():
    """Lê os IDs enviados por CANAL (Telegram e e-mail são independentes).

    A versão antiga usava uma lista simples, apenas para o Telegram.
    Se encontrar esse formato, mantém os IDs como enviados no Telegram,
    mas permite que o e-mail envie essas vagas pela primeira vez.
    """
    if not HISTORY_FILE.exists():
        return {"telegram": set(), "email": set()}

    data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    if isinstance(data, list):  # Compatibilidade com o histórico do MVP antigo.
        return {"telegram": set(map(str, data)), "email": set()}
    if not isinstance(data, dict):
        raise ValueError("O histórico precisa ser uma lista antiga ou objeto por canal.")
    return {
        "telegram": set(map(str, data.get("telegram", []))),
        "email": set(map(str, data.get("email", []))),
    }


def save_history(history):
    """Salva separadamente os IDs de cada canal, sem perder o histórico anterior."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = HISTORY_FILE.with_suffix(".tmp")
    data = {channel: sorted(history[channel]) for channel in ("telegram", "email")}
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(HISTORY_FILE)


def notification_settings():
    """Define quais canais estão ligados (edite SEND_* no .env, não o Python)."""
    def enabled(name):
        value = os.getenv(name, "true").strip().lower()
        if value not in {"true", "false"}:
            raise ValueError(f"{name} deve ser true ou false.")
        return value == "true"

    channels = {"telegram": enabled("SEND_TELEGRAM"), "email": enabled("SEND_EMAIL")}
    if not any(channels.values()):
        raise ValueError("Habilite SEND_TELEGRAM e/ou SEND_EMAIL no .env.")
    return channels


def email_settings(recipient=None):
    """Lê credenciais SMTP necessárias para enviar e-mails, sem expô-las no código."""
    # Para começar: Gmail SMTP (smtp.gmail.com:465 + senha DE APLICATIVO).
    # EMAIL_TO pode conter mais de um e-mail, separado por ponto e vírgula.
    try:
        port = int(os.getenv("SMTP_PORT", "465"))
    except ValueError:
        raise ValueError("SMTP_PORT deve ser um número inteiro.") from None
    if not 1 <= port <= 65535:
        raise ValueError("SMTP_PORT deve estar entre 1 e 65535.")
    return {
        "host": os.getenv("SMTP_HOST", "smtp.gmail.com").strip(),
        "port": port,
        "sender": required_env("EMAIL_FROM"),
        "to": split_terms(recipient if recipient is not None else required_env("EMAIL_TO")),
        "password": required_env("EMAIL_APP_PASSWORD"),
    }


def job_key(job):
    """Identifica uma vaga usando o ID da Jooble ou, na falta dele, seu link."""
    # Futuramente, ao adicionar outras plataformas, vale prefixar a origem do ID.
    return str(job.get("id") or job.get("link") or "")


def relevant(job, excluded, required=None, excluded_companies=None):
    """Aplica filtros simples, configuráveis no .env, ao título e à empresa."""
    title = normalize(job.get("title", ""))
    company = normalize(job.get("company", ""))
    if not title:
        return False  # Não faz sentido enviar uma vaga sem título.

    # Ignora vagas de estágio, aprendiz etc. (conforme EXCLUDED_TITLE_TERMS).
    if any(normalize(term) in title for term in excluded if normalize(term)):
        return False

    # Se você configurar termos obrigatórios, aceita UM deles no título.
    required = required or []
    if required and not any(normalize(term) in title for term in required if normalize(term)):
        return False

    # Permite ignorar empresas indesejadas, sem mexer no código.
    excluded_companies = excluded_companies or []
    if any(normalize(term) in company for term in excluded_companies if normalize(term)):
        return False

    return True


# ========== JOOBLE: BUSCA DE VAGAS ==========
def search_jobs(api_key, keyword, location, radius):
    """Consulta UMA combinação de cargo + cidade na Jooble."""
    # Para integrar outras fontes no futuro, crie uma função parecida para cada API.
    # O campo ResultOnPage define quantas vagas a API pode retornar por consulta.
    response = requests.post(
        API_URL.format(api_key),
        json={
            "keywords": keyword,
            "location": location,
            "radius": radius,
            "page": 1,          # MVP: busca só a primeira página (economiza requisições).
            "ResultOnPage": 20,
        },
        timeout=25,  # Evita o programa ficar preso se a API não responder.
    )
    response.raise_for_status()
    jobs = response.json().get("jobs", [])
    if not isinstance(jobs, list):
        raise ValueError("Resposta da Jooble não contém uma lista de vagas.")
    return jobs


# ========== TELEGRAM: NOTIFICAÇÕES ==========
def job_message(job):
    """Monta a mensagem de cada vaga para o Telegram (que aceita HTML simples)."""
    title = html.escape(job.get("title") or "Cargo não informado")
    company = html.escape(job.get("company") or "Empresa não informada")
    location = html.escape(job.get("location") or "Local não informado")
    salary = html.escape(job.get("salary") or "")
    link = html.escape(job.get("link") or "", quote=True)
    message = f"<b>{title}</b>\n{company} | {location}"
    if salary:  # Muitas vagas não divulgam salário.
        message += f"\nSalário: {salary}"
    if link.startswith("http"):
        message += f'\n<a href="{link}">Abrir vaga</a>'
    return message


def send_telegram(token, chat_id, message):
    """Envia uma mensagem ao chat configurado no .env."""
    try:
        response = requests.post(
            TELEGRAM_URL.format(token, "sendMessage"),
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=25,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        # O token do bot fica na URL; não exibimos a exceção original no terminal/log.
        raise RuntimeError(f"Erro no envio para o Telegram ({type(exc).__name__}).") from None
    if not response.json().get("ok"):
        raise RuntimeError("Telegram recusou a mensagem. Confira token e chat ID.")


def show_chat_ids():
    """Mostra os chats que enviaram mensagens ao bot (útil para configurar o .env)."""
    token = required_env("TELEGRAM_BOT_TOKEN")
    try:
        response = requests.get(TELEGRAM_URL.format(token, "getUpdates"), timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Erro ao buscar chat ID ({type(exc).__name__}).") from None

    chats = set()
    for update in response.json().get("result", []):
        for key in ("message", "channel_post", "my_chat_member"):
            chat = update.get(key, {}).get("chat", {})
            if chat.get("id") is not None:
                chats.add((str(chat["id"]), str(chat.get("type", ""))))

    if chats:
        for chat_id, kind in sorted(chats):
            print(f"Chat ID: {chat_id} ({kind})")
    else:
        print("Nenhum chat encontrado. Envie /start ao bot no Telegram e tente de novo.")


# ========== E-MAIL: NOTIFICAÇÕES ==========
def send_email(config, jobs):
    """Monta um e-mail com os links e envia usando SMTP seguro (SSL na porta 465).

    "jobs" é uma lista de vagas (dicionários), não uma mensagem HTML pronta.
    Assim, o mesmo resultado da busca serve para o Telegram e para o e-mail.
    """
    subject = f"Job Hunter | {len(jobs)} nova(s) vaga(s) de engenharia"
    email = EmailMessage()
    email["From"] = config["sender"]
    email["To"] = ", ".join(config["to"])
    email["Subject"] = subject

    # Corpo em texto: funciona até em clientes que não mostram HTML.
    lines = ["BOT: Novas oportunidades encontradas:", ""]
    for job in jobs:
        lines.extend([
            job.get("title") or "Cargo não informado",
            f"Empresa: {job.get('company') or 'Não informada'}",
            f"Local: {job.get('location') or 'Não informado'}",
            f"Link: {job.get('link') or 'Não informado'}",
            "",
        ])
    email.set_content("\n".join(lines))

    # Corpo HTML: mantém as vagas organizadas, com links clicáveis.
    blocks = []
    for job in jobs:
        title = html.escape(job.get("title") or "Cargo não informado")
        company = html.escape(job.get("company") or "Empresa não informada")
        location = html.escape(job.get("location") or "Local não informado")
        url = html.escape(job.get("link") or "", quote=True)
        salary = html.escape(job.get("salary") or "")
        salary_html = f"<p><strong>Salário:</strong> {salary}</p>" if salary else ""
        link_html = f'<a href="{url}">Ver vaga</a>' if url.startswith("http") else ""
        blocks.append(
            f"<div style='margin-bottom:20px'>"
            f"<h3>{title}</h3><p>{company} | {location}</p>"
            f"{salary_html}{link_html}</div>"
        )
    email.add_alternative(
        "<html><body><h2>Novas vagas encontradas</h2>"
        + "".join(blocks) + "</body></html>",
        subtype="html",
    )

    # Gmail: smtp.gmail.com, porta 465, senha de aplicativo.
    # Em outro provedor, personalize SMTP_HOST e SMTP_PORT no .env.
    # Nunca use sua senha normal do Gmail no EMAIL_APP_PASSWORD.
    with smtplib.SMTP_SSL(
        config["host"], config["port"], context=ssl.create_default_context(), timeout=25
    ) as smtp:
        smtp.login(config["sender"], config["password"])
        smtp.send_message(email)


def telegram_batches(selected):
    """Divide as vagas em mensagens menores que o limite do Telegram."""
    batch, ids, batches = [], [], []
    for key, job in selected:
        part = job_message(job)
        if batch and len("\n\n".join(batch + [part])) > 3300:
            batches.append((ids, batch))
            batch, ids = [], []
        batch.append(part)
        ids.append(key)
    if batch:
        batches.append((ids, batch))
    return batches


def print_preview(selected_by_channel):
    """Mostra o que cada canal receberia, sem enviar nem salvar nada."""
    for channel, selected in selected_by_channel.items():
        print(f"\nPREVIEW ({channel}): {len(selected)} vagas inéditas:")
        for _, job in selected:
            print(f"- {job.get('title', 'Sem título')} | {job.get('company', 'Empresa não informada')}")
            print(f"  {job.get('location', 'Local não informado')} | {job.get('link', '')}")
    print("Preview finalizado. Nenhuma mensagem enviada e nenhum ID salvo.")


# ========== EXECUÇÃO PRINCIPAL ==========
def main(preview=False):
    """Orquestra busca -> filtros -> histórico -> Telegram E e-mail."""
    settings = get_settings()
    count = search_count(settings)

    # Cada combinação cargo/cidade custa uma consulta da cota da Jooble.
    if count > settings["max_queries"]:
        raise RuntimeError(
            f"Você configurou {count} buscas, mas MAX_QUERIES_PER_RUN="
            f"{settings['max_queries']}. Execute --plan para conferir."
        )

    # Expande os perfis com sinônimos locais sem ultrapassar a cota configurada.
    if settings["profile"] != "custom":
        settings["keywords"] = effective_keywords(settings)
        count = search_count(settings)

    api_key = required_env("JOOBLE_API_KEY")
    channels = notification_settings()

    # Valida credenciais ANTES da busca para não gastar Jooble à toa.
    # No --preview não acessamos nenhum canal de envio.
    telegram_credentials = None
    mail_config = None
    if not preview:
        if channels["telegram"]:
            telegram_credentials = (
                required_env("TELEGRAM_BOT_TOKEN"), required_env("TELEGRAM_CHAT_ID")
            )
        if channels["email"]:
            mail_config = email_settings()

    history = load_history()
    candidates = {}  # Mesmo ID em duas buscas? Entra só uma vez.
    errors = 0
    review_candidates = {}
    below_count = 0

    for location in settings["locations"]:
        for keyword in settings["keywords"]:
            try:
                jobs = search_jobs(api_key, keyword, location, settings["radius"])
                print(f"Busca '{keyword}' em '{location}': {len(jobs)} vagas recebidas.")
                for job in jobs:
                    key = job_key(job)
                    if (
                        key
                        and job.get("link")
                        and relevant(
                            job,
                            settings["excluded_titles"],
                            settings["required_titles"],
                            settings["excluded_companies"],
                        )
                    ):
                        assessment = matching.assess(job, settings["profile"], settings["keywords"], True, settings["excluded_titles"])
                        if not assessment["matched"]:
                            continue
                        job = {**job, "country": job.get("country") or "BR", "match": assessment}
                        check = salary.evaluate(job, settings["salary_min"])
                        job["salary_check"] = check
                        if check["status"] == "eligible":
                            candidates[key] = job
                        elif check["status"] == "review":
                            review_candidates[key] = job
                        else:
                            below_count += 1
            except (requests.RequestException, ValueError) as exc:
                # Erros de HTTP podem conter a chave na URL, então não mostramos o texto.
                errors += 1
                print(f"Erro na busca '{keyword}' em '{location}' ({type(exc).__name__}).")

    if errors == count:
        raise RuntimeError("Todas as buscas falharam. Confira a chave, a rede e a API.")
    print(f"Piso: R$ {settings['salary_min']:,.0f}/mês. {len(candidates)} vagas com salário compatível; "
          f"{len(review_candidates)} para análise; {below_count} resultados abaixo do piso.")
    if preview:
        for job in review_candidates.values():
            print(f"PARA ANÁLISE (sem alerta): {job['title']} | {job.get('salary') or 'salário não informado'} | {job.get('link', '')}")
    else:
        review_path = HISTORY_FILE.parent / "salary_review.json"
        review_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = review_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(list(review_candidates.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(review_path)

    # Cada canal tem SEU histórico: se o e-mail falhar, na próxima execução
    # apenas ele tentará novamente, sem repetir o Telegram que já funcionou.
    candidates_sorted = sorted(
        candidates.items(), key=lambda item: item[1].get("updated") or "", reverse=True
    )
    selected_by_channel = {
        channel: [
            (key, job) for key, job in candidates_sorted if key not in history[channel]
        ][:settings["max_jobs"]]
        for channel, is_enabled in channels.items() if is_enabled
    }

    if preview:
        print_preview(selected_by_channel)
        return

    if not any(selected_by_channel.values()):
        print("Nenhuma vaga inédita passou pelos filtros dos canais ativados.")
        return

    send_errors = []

    # Primeiro o Telegram. Cada lote enviado é salvo imediatamente no histórico.
    if channels["telegram"]:
        selected = selected_by_channel["telegram"]
        if selected:
            try:
                token, chat_id = telegram_credentials
                for ids, parts in telegram_batches(selected):
                    message = "<b>Novas vagas — Engenharia de Produto e Produção</b>\n\n" + "\n\n".join(parts)
                    send_telegram(token, chat_id, message)
                    history["telegram"].update(ids)
                    save_history(history)
                    print(f"Telegram: {len(ids)} vaga(s) enviadas.")
            except (RuntimeError, OSError, ValueError) as exc:
                send_errors.append("Telegram")
                print(f"Falha no Telegram ({type(exc).__name__}).")

    # Depois o e-mail. Se o Telegram falhar, o e-mail ainda será tentado.
    if channels["email"]:
        selected = selected_by_channel["email"]
        if selected:
            try:
                send_email(mail_config, [job for _, job in selected])
                history["email"].update(key for key, _ in selected)
                save_history(history)
                print(f"E-mail: {len(selected)} vaga(s) enviadas.")
            except (smtplib.SMTPException, OSError, RuntimeError, ValueError) as exc:
                # Não imprimir a exceção completa evita vazar usuário/credenciais.
                send_errors.append("e-mail")
                print(f"Falha no e-mail ({type(exc).__name__}).")

    if send_errors:
        raise RuntimeError("O envio falhou em: " + ", ".join(send_errors) + ".")


if __name__ == "__main__":
    # Escolha um comando. O padrão (sem flags) busca e envia as vagas.
    parser = argparse.ArgumentParser(description="Job Hunter Bot")
    parser.add_argument("--plan", action="store_true", help="Mostra o plano e o consumo, sem chamar APIs")
    parser.add_argument("--chat-id", action="store_true", help="Descobre o ID do seu chat no Telegram")
    parser.add_argument("--test-telegram", action="store_true", help="Envia só uma mensagem de teste ao bot")
    parser.add_argument("--test-email", action="store_true", help="Envia só um e-mail de teste")
    parser.add_argument("--preview", action="store_true", help="Busca vagas, mas não envia nem salva IDs")
    args = parser.parse_args()

    if args.plan:
        show_plan(get_settings())
    elif args.chat_id:
        show_chat_ids()
    elif args.test_telegram:
        send_telegram(
            required_env("TELEGRAM_BOT_TOKEN"),
            required_env("TELEGRAM_CHAT_ID"),
            "<b>Job Hunter Bot</b> — teste de notificação funcionando!",
        )
        print("Mensagem de teste enviada ao Telegram.")
    elif args.test_email:
        send_email(email_settings(), [{
            "title": "Teste de notificação do Job Hunter Bot",
            "company": "Mensagem de teste",
            "location": "Sem busca na Jooble",
            "link": "https://br.jooble.org/",
        }])
        print("E-mail de teste enviado.")
    else:
        main(preview=args.preview)
