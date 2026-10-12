"""Testes offline: API da Jooble, Telegram e Gmail são simulados (mocks)."""

import json
import smtplib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


# Dados falsos para não consumir consultas nem disparar notificações.
JOB = {
    "id": 111,
    "title": "Engenheiro de Produção",
    "company": "Indústria Exemplo",
    "location": "Curitiba",
    "link": "https://example.com/111",
    "updated": "2026-10-09T10:00:00",
    "salary": "R$ 8.000 mensal",
}

ENV = {
    "JOOBLE_API_KEY": "chave-falsa",
    "TELEGRAM_BOT_TOKEN": "token-falso",
    "TELEGRAM_CHAT_ID": "123",
    "EMAIL_FROM": "teste@gmail.com",
    "EMAIL_TO": "pai@gmail.com",
    "EMAIL_APP_PASSWORD": "senha-de-teste",
    "JOB_LOCATION": "Curitiba",
    "JOB_KEYWORDS": "engenheiro",
    "SEND_EMAIL": "true",
    "SEND_TELEGRAM": "true",
}


class JobHunterTests(unittest.TestCase):
    def setUp(self):
        # Cada teste usa seu proprio historico, sem acessar o banco real do .env.
        env = patch.dict("os.environ", {"DATABASE_URL": ""})
        env.start()
        self.addCleanup(env.stop)

        self.budget_patch = patch.object(main, 'make_usage_budget', return_value=None)
        self.budget_patch.start()
        self.addCleanup(self.budget_patch.stop)

    def test_normalize_removes_accents(self):
        self.assertEqual(main.normalize("Engenheiro de Produção"), "engenheiro de producao")

    def test_excludes_internships(self):
        self.assertFalse(main.relevant({"title": "Estagiário de Produção"}, ["estagiário"]))
        self.assertTrue(main.relevant({"title": "Engenheiro de Processos"}, ["estagiário"]))

    def test_optional_title_and_company_filters(self):
        job = {"title": "Coordenador de Melhoria Contínua", "company": "Fábrica Exemplo"}
        self.assertTrue(main.relevant(job, [], ["engenheiro", "coordenador"], []))
        self.assertFalse(main.relevant(job, [], ["gerente"], []))
        self.assertFalse(main.relevant(job, [], [], ["fabrica exemplo"]))

    def test_queries_count(self):
        with patch.dict("os.environ", {
            "JOB_KEYWORDS": "engenheiro;coordenador;gerente",
            "JOB_LOCATIONS": "Curitiba;Ponta Grossa",
        }, clear=True):
            self.assertEqual(main.search_count(main.get_settings()), 6)

    def test_limit_prevents_unexpected_api_calls(self):
        env = {**ENV, "JOB_KEYWORDS": "engenheiro;coordenador;gerente", "MAX_QUERIES_PER_RUN": "2"}
        with patch.dict("os.environ", env, clear=True), patch.object(main, "search_jobs") as api:
            with self.assertRaisesRegex(RuntimeError, "MAX_QUERIES_PER_RUN"):
                main.main(preview=True)
            api.assert_not_called()

    def test_history_roundtrip_per_channel(self):
        with tempfile.TemporaryDirectory() as folder:
            history_file = Path(folder) / "data" / "sent_jobs.json"
            with patch.object(main, "HISTORY_FILE", history_file):
                main.save_history({"telegram": {"123"}, "email": {"456"}})
                self.assertEqual(main.load_history(), {"telegram": {"123"}, "email": {"456"}})
                self.assertEqual(json.loads(history_file.read_text(encoding="utf-8")),
                                 {"telegram": ["123"], "email": ["456"]})

    def test_old_history_list_migrates_without_resending_telegram(self):
        with tempfile.TemporaryDirectory() as folder:
            history_file = Path(folder) / "data" / "sent_jobs.json"
            history_file.parent.mkdir(parents=True)
            history_file.write_text('["111", "222"]', encoding="utf-8")
            with patch.object(main, "HISTORY_FILE", history_file):
                self.assertEqual(main.load_history(), {"telegram": {"111", "222"}, "email": set()})

    def test_job_message_escapes_html(self):
        msg = main.job_message({
            "title": "P&D <Sênior>",
            "company": "A & B",
            "location": "Curitiba",
            "link": "https://example.com?a=1&b=2",
        })
        self.assertIn("P&amp;D &lt;Sênior&gt;", msg)
        self.assertIn("A &amp; B", msg)
        self.assertIn("a=1&amp;b=2", msg)

    def test_invalid_channel_configuration(self):
        with patch.dict("os.environ", {"SEND_TELEGRAM": "false", "SEND_EMAIL": "false"}, clear=True):
            with self.assertRaisesRegex(ValueError, "Habilite"):
                main.notification_settings()

    def test_preview_does_not_send_or_save(self):
        with tempfile.TemporaryDirectory() as folder:
            history_file = Path(folder) / "data" / "sent_jobs.json"
            with patch.object(main, "HISTORY_FILE", history_file), \
                 patch.dict("os.environ", ENV, clear=True), \
                 patch.object(main, "search_jobs", return_value=[JOB]), \
                 patch.object(main, "send_telegram") as telegram, \
                 patch.object(main, "send_email") as email:
                main.main(preview=True)
                telegram.assert_not_called()
                email.assert_not_called()
                self.assertFalse(history_file.exists())

    def test_both_channels_receive_and_save(self):
        with tempfile.TemporaryDirectory() as folder:
            history_file = Path(folder) / "data" / "sent_jobs.json"
            with patch.object(main, "HISTORY_FILE", history_file), \
                 patch.dict("os.environ", ENV, clear=True), \
                 patch.object(main, "search_jobs", return_value=[JOB]), \
                 patch.object(main, "send_telegram") as telegram, \
                 patch.object(main, "send_email") as email:
                main.main()
                telegram.assert_called_once()
                email.assert_called_once()
                self.assertEqual(main.load_history(), {"telegram": {"111"}, "email": {"111"}})
                # O segundo ciclo não pode enviar a mesma vaga em nenhum canal.
                main.main()
                telegram.assert_called_once()
                email.assert_called_once()

    def test_telegram_failure_still_sends_email(self):
        with tempfile.TemporaryDirectory() as folder:
            history_file = Path(folder) / "data" / "sent_jobs.json"
            with patch.object(main, "HISTORY_FILE", history_file), \
                 patch.dict("os.environ", ENV, clear=True), \
                 patch.object(main, "search_jobs", return_value=[JOB]), \
                 patch.object(main, "send_telegram", side_effect=RuntimeError("falhou")), \
                 patch.object(main, "send_email") as email:
                with self.assertRaisesRegex(RuntimeError, "Telegram"):
                    main.main()
                email.assert_called_once()
                self.assertEqual(main.load_history(), {"telegram": set(), "email": {"111"}})

    def test_email_failure_does_not_resend_successful_telegram(self):
        with tempfile.TemporaryDirectory() as folder:
            history_file = Path(folder) / "data" / "sent_jobs.json"
            with patch.object(main, "HISTORY_FILE", history_file), \
                 patch.dict("os.environ", ENV, clear=True), \
                 patch.object(main, "search_jobs", return_value=[JOB]), \
                 patch.object(main, "send_telegram") as telegram, \
                 patch.object(main, "send_email", side_effect=smtplib.SMTPException("falhou")) as email:
                with self.assertRaisesRegex(RuntimeError, "e-mail"):
                    main.main()
                self.assertEqual(main.load_history(), {"telegram": {"111"}, "email": set()})
                with self.assertRaisesRegex(RuntimeError, "e-mail"):
                    main.main()
                telegram.assert_called_once()  # Telegram não recebe duas vezes!
                self.assertEqual(email.call_count, 2)  # E-mail tenta novamente.

    def test_can_disable_telegram_and_only_send_email(self):
        with tempfile.TemporaryDirectory() as folder:
            history_file = Path(folder) / "data" / "sent_jobs.json"
            with patch.object(main, "HISTORY_FILE", history_file), \
                 patch.dict("os.environ", {**ENV, "SEND_TELEGRAM": "false"}, clear=True), \
                 patch.object(main, "search_jobs", return_value=[JOB]), \
                 patch.object(main, "send_telegram") as telegram, \
                 patch.object(main, "send_email") as email:
                main.main()
                telegram.assert_not_called()
                email.assert_called_once()
                self.assertEqual(main.load_history(), {"telegram": set(), "email": {"111"}})

    def test_send_email_builds_text_and_html_without_network(self):
        with patch.object(main.smtplib, "SMTP_SSL") as smtp_ssl:
            smtp_ssl.return_value.__enter__.return_value = smtp_ssl.return_value
            config = {
                "host": "smtp.gmail.com", "port": 465,
                "sender": "teste@gmail.com", "to": ["pai@gmail.com"],
                "password": "senha-de-teste",
            }
            main.send_email(config, [{**JOB, "title": "P&D <Sênior>"}])
            smtp_ssl.return_value.login.assert_called_once_with("teste@gmail.com", "senha-de-teste")
            message = smtp_ssl.return_value.send_message.call_args.args[0]
            self.assertIn("pai@gmail.com", message["To"])
            self.assertIn("https://example.com/111", message.get_body(preferencelist=("plain",)).get_content())
            self.assertIn("P&amp;D &lt;Sênior&gt;", message.get_body(preferencelist=("html",)).get_content())


if __name__ == "__main__":
    unittest.main()
