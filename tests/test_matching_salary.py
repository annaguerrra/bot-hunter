"""Regressões da lista enviada pela usuária e contratos de salário/IA."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
import main
from jobhunter import gemini, matching, providers, salary
from web import create_app, validate_filters

COMPANY = {"id": 1, "name": "Bosch", "enabled": 1, "provider": "smartrecruiters", "identifier": "BoschGroup"}
FORM = {"keywords": "engenheiro de produto;engenheiro de produção", "sources": ["companies"], "company_ids": [1]}


def job(title="Product Engineer", pay="R$ 8.000 mensal", path="1", **extra):
    return providers.make_job(title, "Bosch", "Curitiba, Brasil", "https://jobs.example.org/" + path,
                              "Bosch", country="BR", salary=pay, **extra)


class ProviderSalaryTests(unittest.TestCase):
    def test_jobposting_base_salary_is_parsed_without_generated_estimates(self):
        item = {"@type": "JobPosting", "title": "Product Engineer", "url": "https://example.org/jobs/1",
                "baseSalary": {"@type": "MonetaryAmount", "currency": "BRL", "value": {"minValue": 8000, "maxValue": 10000, "unitText": "MONTH"}}}
        html = '<script type="application/ld+json">' + json.dumps(item) + '</script>'
        found, _ = providers.extract_jobpostings(html, item["url"], "Example")
        self.assertEqual(salary.evaluate(found[0])["status"], "eligible")


class IntegrationTests(unittest.TestCase):
    def test_jooble_catalog_lists_real_domains_and_rejects_unsupported_market(self):
        from jobhunter.jooble_markets import MARKETS, HOSTS
        self.assertEqual(len(MARKETS), 66)
        self.assertEqual(len(HOSTS), 66)
        self.assertEqual(HOSTS["GB"], "uk.jooble.org")
        self.assertEqual(HOSTS["JP"], "ja.jooble.org")
        self.assertEqual(HOSTS["US"], "jooble.org")
        self.assertNotIn("CN", HOSTS)
        with self.assertRaises(providers.NeedsConfiguration):
            providers.jooble(validate_filters({**FORM, "sources": ["jooble"], "country": "CN"}, [COMPANY]))

    def test_native_company_salary_interval_and_details_are_used(self):
        original = job(pay="") | {"detail_url": "https://api.smartrecruiters.com/v1/companies/BoschGroup/postings/1"}
        payload = {"active": True, "jobAd": {"sections": {"companyDescription": {"text": "Company boilerplate " * 100}, "jobDescription": {"text": "Mechanical product development"}}},
                   "compensation": {"min": 84000, "max": 96000, "currency": "BRL", "period": "YEARLY"}}
        with patch.object(providers, "public_json", return_value=payload):
            found, _ = providers.enrich_company_jobs(COMPANY, [original], validate_filters(FORM, [COMPANY]))
        self.assertTrue(found[0]["description"].startswith("Mechanical"))
        self.assertEqual(salary.evaluate(found[0])["monthly_brl"], 7000)

    def test_gemini_quota_error_is_actionable_without_echoing_api_body(self):
        response = requests.Response()
        response.status_code = 429
        response._content = b'{"error":{"message":"secret-must-never-be-echoed"}}'
        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key", "GEMINI_ENABLED": "true"}), patch.object(requests, "post", return_value=response):
            with self.assertRaises(gemini.GeminiError) as error:
                gemini.generate("find jobs", True)
        self.assertIn("429", str(error.exception))
        self.assertIn("cotas", str(error.exception))
        self.assertNotIn("secret-must-never-be-echoed", str(error.exception))

    def test_providers_separate_review_and_remove_wrong_area_and_underpaid(self):
        found = [job(), job(pay="", path="review"), job(pay="R$ 2600 mensal", path="low"), job("Engenheiro Civil", path="civil")]
        filters = validate_filters(FORM, [COMPANY])
        with patch.dict(providers.COMPANY_PROVIDERS, {"smartrecruiters": lambda company, query: (found, [])}):
            result = providers.run_search(filters, [COMPANY])
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(len(result["review_jobs"]), 1)
        self.assertEqual(result["reports"][0]["below_minimum"], 1)

    def test_cli_unknown_salary_never_sends_and_preview_does_not_save(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(main, "HISTORY_FILE", Path(directory) / "history.json"), \
             patch.dict("os.environ", {"JOB_LOCATION": "Curitiba", "JOB_KEYWORDS": "engenheiro de produto", "JOOBLE_API_KEY": "fake"}, clear=True), \
             patch.object(main, "search_jobs", return_value=[job(pay="")]), patch.object(main, "send_telegram") as telegram, \
             patch.object(main, "send_email") as email, contextlib.redirect_stdout(io.StringIO()) as output:
            main.main(preview=True)
            telegram.assert_not_called()
            email.assert_not_called()
            self.assertEqual([path.name for path in Path(directory).iterdir()], ['hunter.sqlite'])
            self.assertIn("PARA ANÁLISE", output.getvalue())

    def test_gemini_missing_key_preserves_other_sources(self):
        filters = validate_filters({**FORM, "sources": ["companies", "gemini"]}, [COMPANY])
        with patch.dict("os.environ", {}, clear=True), patch.dict(providers.COMPANY_PROVIDERS, {"smartrecruiters": lambda company, query: ([job()], [])}):
            result = providers.run_search(filters, [COMPANY])
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["reports"][1]["status"], "pending")

    def test_gemini_uses_key_header_search_tool_and_no_secret_in_prompt(self):
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"candidates": [{"content": {"parts": [{"text": '{"pages": []}'}]}, "groundingMetadata": {"webSearchQueries": ["product engineer jobs"]}}]}).encode()
        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-private-key", "GEMINI_ENABLED": "true"}), patch.object(requests, "post", return_value=response) as network:
            data, metadata = gemini.generate("find jobs", search=True)
        call = network.call_args
        self.assertEqual(call.kwargs["headers"]["x-goog-api-key"], "fake-private-key")
        self.assertNotIn("fake-private-key", call.args[0])
        self.assertNotIn("fake-private-key", json.dumps(call.kwargs["json"]))
        self.assertEqual(call.kwargs["json"]["tools"], [{"google_search": {}}])
        self.assertFalse(call.kwargs["json"]["store"])
        self.assertEqual(data, {"pages": []})

    def test_gemini_only_imports_verified_cited_jobposting_not_invented_salary(self):
        url = "https://jobs.example.org/verified"
        model = {"pages": [{"url": "http://127.0.0.1/private", "salary": "BRL 99999 monthly"}, {"url": url, "salary": "BRL 99999 monthly"}]}
        grounding = {"groundingChunks": [{"web": {"uri": url, "title": "Employer"}}], "searchEntryPoint": {"renderedContent": "<div>Google</div>"}}
        html = '<script type="application/ld+json">' + json.dumps({"@type": "JobPosting", "title": "Product Engineer", "url": url}) + '</script>'
        with patch.object(gemini, "generate", return_value=(model, grounding)), patch.object(providers, "robots_allows", return_value=True), patch.object(providers, "public_get", return_value=html) as fetch:
            found, notes, refs, queries, suggestions = gemini.search_jobs(validate_filters(FORM, [COMPANY]))
        fetch.assert_called_once_with(url)
        self.assertEqual(found[0]["salary"], "")
        self.assertEqual(salary.evaluate(found[0])["status"], "review")
        self.assertEqual(refs[0]["url"], url)
        self.assertIn("Google", suggestions)

    def test_gemini_rank_cannot_change_salary_or_create_jobs(self):
        original = job(pay="")
        original["salary_check"] = salary.evaluate(original)
        ranking = {"rankings": [{"id": original["id"], "score": 99, "reason": "Produto físico", "salary": "90000"}, {"id": "invented", "score": 100, "reason": "fake"}]}
        with patch.object(gemini, "generate", return_value=(ranking, {})):
            result = gemini.rank_jobs([original], "product")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["salary_check"]["status"], "review")
        self.assertEqual(result[0]["salary"], "")
        self.assertEqual(result[0]["ai_assessment"]["score"], 99)

    def test_web_rejects_bypassing_unknown_salary_even_for_saved_historical_job(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / "db.sqlite")
            client = app.test_client()
            import re
            token = re.search(r'name="hunter-csrf" content="([^"]+)"', client.get("/").get_data(as_text=True)).group(1)
            account = client.post('/api/auth/register', json={'name': 'Tester', 'email': 'tester@example.org', 'password': 'test-password-long'}, headers={'X-Hunter-CSRF': token})
            token = account.json['csrf']
            old = job(pay="")
            app.extensions['store'].favorite(old, user_id=account.json['user']['id'])
            with patch.object(main, "send_telegram") as send:
                result = client.post("/api/notify", json={"ids": [old["id"]], "channels": ["telegram"]}, headers={"X-Hunter-CSRF": token})
            send.assert_not_called()
            self.assertEqual(result.status_code, 400)
            app.extensions["executor"].shutdown(wait=True)

    def test_old_high_salary_civil_job_cannot_bypass_engineering_area_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / "db.sqlite")
            client = app.test_client()
            import re
            token = re.search(r'name="hunter-csrf" content="([^"]+)"', client.get("/").get_data(as_text=True)).group(1)
            account = client.post('/api/auth/register', json={'name': 'Tester', 'email': 'tester@example.org', 'password': 'test-password-long'}, headers={'X-Hunter-CSRF': token})
            token = account.json['csrf']
            old = job("Coordenador de Obras - Engenheiro Civil", pay="R$ 9000 mensal")
            app.extensions['store'].favorite(old, user_id=account.json['user']['id'])
            with patch.object(main, "send_telegram") as send:
                response = client.post("/api/notify", json={"ids": [old["id"]], "channels": ["telegram"]}, headers={"X-Hunter-CSRF": token})
            send.assert_not_called()
            self.assertEqual(response.status_code, 400)
            app.extensions["executor"].shutdown(wait=True)

    def test_salary_filter_cannot_lower_floor_or_use_nan(self):
        for value in [2600, -1, "7000", float("nan"), float("inf")]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_filters({**FORM, "salary_min": value}, [COMPANY])


if __name__ == "__main__":
    unittest.main()
