"""Testes de contrato da aplicação web. Sem consultas ou envios externos."""
import json
import re
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

import main
from jobhunter import geo, providers
from jobhunter.storage import Store
from web import create_app, validate_filters

COMPANY = {"id": 1, "name": "Bosch", "url": "https://careers.bosch.com/", "provider": "smartrecruiters", "identifier": "BoschGroup", "enabled": 1}
FORM = {"keywords": "production engineer", "sources": ["companies"], "company_ids": [1]}


def example_job(country="DE", location="Stuttgart, Baden-Württemberg, Germany", title="Production Engineer", link="https://jobs.example.org/123"):
    return providers.make_job(title, "Bosch", location, link, "Bosch", country=country, state="Baden-Württemberg", salary="BRL 8,000 per month")


class GeographyTests(unittest.TestCase):
    def test_catalog_contains_all_iso_countries_and_subdivisions(self):
        self.assertGreaterEqual(len(geo.COUNTRIES), 249)
        self.assertEqual(geo.BY_CODE["CN"]["region"], "AS")
        self.assertEqual(geo.BY_CODE["BR"]["region"], "AM")
        self.assertEqual(geo.BY_CODE["DE"]["region"], "EU")
        self.assertIn("BR-PR", [item["code"] for item in geo.states("BR")])
        self.assertIn("DE-BW", [item["code"] for item in geo.states("DE")])

    def test_country_region_and_state_must_agree(self):
        for changes in ({"region": "AS", "country": "BR"}, {"country": "DE", "state": "BR-PR"}, {"state": "BR-PR"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_filters({**FORM, **changes}, [COMPANY])

    def test_filters_do_not_include_wrong_or_unknown_country(self):
        filters = validate_filters({**FORM, "region": "EU", "country": "DE", "state": "DE-BW"}, [COMPANY])
        self.assertTrue(geo.location_matches(example_job(), filters))
        self.assertFalse(geo.location_matches(example_job(country="BR"), filters))
        self.assertFalse(geo.location_matches(example_job(country="DE", location="Berlin, Germany") | {"state": "Berlin"}, filters))
        self.assertFalse(geo.location_matches(example_job(country="", location="Remote") | {"country": ""}, filters))

    def test_oversized_queries_and_invalid_option_types_are_rejected(self):
        for changes in ({"keywords": "a;b;c;d"}, {"keywords": "x" * 301}, {"pages": 20}, {"remote": "false"}, {"sources": ["unknown"]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_filters({**FORM, **changes}, [COMPANY])


class ProviderTests(unittest.TestCase):
    def test_company_platform_detection(self):
        self.assertEqual(providers.detect_provider("https://careers.bosch.com/"), ("smartrecruiters", "BoschGroup"))
        self.assertEqual(providers.detect_provider("https://jobs.lever.co/example"), ("lever", "example"))
        self.assertEqual(providers.detect_provider("https://job-boards.greenhouse.io/example"), ("greenhouse", "example"))
        self.assertEqual(providers.detect_provider("https://careers.bosch.com.evil.example/"), ("website", ""))

    def test_state_abbreviation_is_not_mistaken_for_a_country(self):
        job = providers.make_job("Engineer", "Example", "San Francisco, CA", "https://example.org/1", "Greenhouse")
        self.assertEqual(job["country"], "")
        explicit = providers.make_job("Engineer", "Example", "San Francisco, CA", "https://example.org/1", "Example", country="US")
        self.assertEqual(explicit["country"], "US")

    def test_internal_addresses_are_not_fetchable(self):
        for address in ("127.0.0.1", "10.0.0.8", "169.254.169.254", "::1", "fd00::1"):
            with self.subTest(address=address), patch.object(socket, "getaddrinfo", return_value=[(None, None, None, None, (address, 443))]):
                with self.assertRaises(ValueError):
                    providers.validate_url("https://example.org/jobs")

    def test_redirect_to_private_address_is_blocked(self):
        response = requests.Response()
        response.status_code = 302
        response.headers["Location"] = "http://127.0.0.1/private"
        def resolve(host, *args, **kwargs):
            return [(None, None, None, None, ("127.0.0.1" if host == "127.0.0.1" else "93.184.216.34", 443))]
        with patch.object(socket, "getaddrinfo", side_effect=resolve), patch.object(requests, "get", return_value=response):
            with self.assertRaises(ValueError):
                providers.public_get("https://example.org/jobs")

    def test_jobposting_graph_multiple_locations_and_expired_jobs(self):
        data = {"@graph": [
            {"@type": "JobPosting", "title": "Production Engineer", "url": "/jobs/42", "hiringOrganization": {"name": "Example"},
             "jobLocation": [{"address": {"addressCountry": "DE", "addressLocality": "Berlin"}}, {"address": {"addressCountry": "BR", "addressLocality": "Curitiba"}}]},
            {"@type": "JobPosting", "title": "Expired", "validThrough": "2020-01-01"},
        ]}
        html = '<script type="application/ld+json">' + json.dumps(data) + '</script><script type="application/ld+json">invalid</script>'
        found, _ = providers.extract_jobpostings(html, "https://example.org/careers", "Example")
        self.assertEqual(len(found), 2)
        self.assertEqual({job["country"] for job in found}, {"DE", "BR"})
        self.assertTrue(all(job["link"] == "https://example.org/jobs/42" for job in found))

    def test_bosch_mapping_uses_country_filter_and_real_apply_link(self):
        payload = {"totalFound": 1, "content": [{"id": "42", "name": "Production Engineer", "company": {"name": "Bosch"}, "location": {"city": "Stuttgart", "country": "de", "region": "Baden-Württemberg"}}]}
        filters = validate_filters({**FORM, "country": "DE"}, [COMPANY])
        with patch.object(providers, "public_json", return_value=payload) as fetch:
            found, _ = providers.smartrecruiters(COMPANY, filters)
        self.assertEqual(fetch.call_args.args[1]["country"], "de")
        self.assertEqual(fetch.call_args.args[1]["q"], '"production engineer"')
        self.assertEqual(found[0]["country"], "DE")
        self.assertEqual(found[0]["link"], "https://jobs.smartrecruiters.com/BoschGroup/42")

    def test_missing_google_key_does_not_discard_company_results(self):
        filters = validate_filters({**FORM, "sources": ["companies", "google"]}, [COMPANY])
        with patch.dict("os.environ", {}, clear=True), patch.dict(providers.COMPANY_PROVIDERS, {"smartrecruiters": lambda company, query: ([example_job()], [])}):
            result = providers.run_search(filters, [COMPANY])
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["reports"][1]["status"], "pending")

    def test_title_filter_rejects_unrelated_coordinator(self):
        filters = validate_filters({**FORM, "keywords": "coordenador de produção"}, [COMPANY])
        jobs = [example_job(title="Coordenador Comercial"), example_job(title="Coordenador de Produção Industrial", link="https://example.org/2")]
        with patch.dict(providers.COMPANY_PROVIDERS, {"smartrecruiters": lambda company, query: (jobs, [])}):
            result = providers.run_search(filters, [COMPANY])
        self.assertEqual([job["title"] for job in result["jobs"]], ["Coordenador de Produção Industrial"])

    def test_google_uses_current_pagination_and_normalizes_results(self):
        first = {"jobs_results": [{"title": "Production Engineer", "company_name": "Example", "location": "Berlin, Germany", "apply_options": [{"link": "javascript:alert(1)"}, {"link": "https://example.org/42"}]}], "serpapi_pagination": {"next_page_token": "page-2"}}
        second = {"jobs_results": []}
        response1, response2 = requests.Response(), requests.Response()
        for response, payload in ((response1, first), (response2, second)):
            response.status_code = 200
            response._content = json.dumps(payload).encode()
        filters = validate_filters({**FORM, "country": "DE", "pages": 2}, [COMPANY])
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "fake-key"}), patch.object(requests, "get", side_effect=[response1, response2]) as fetch:
            found, _ = providers.google_jobs(filters)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["link"], "https://example.org/42")
        self.assertEqual(fetch.call_args_list[1].kwargs["params"]["next_page_token"], "page-2")
        self.assertNotIn("start", fetch.call_args_list[1].kwargs["params"])

    def test_jooble_does_not_send_brazilian_key_to_another_country(self):
        filters = validate_filters({**FORM, "sources": ["jooble"], "country": "DE"}, [COMPANY])
        with patch.dict("os.environ", {"JOOBLE_API_KEY": "br-only"}, clear=True), patch.object(requests, "post") as network:
            result = providers.run_search(filters, [COMPANY])
        network.assert_not_called()
        self.assertEqual(result["reports"][0]["status"], "pending")
        self.assertIn("Alemanha", result["reports"][0]["notes"][0])

    def test_jooble_regional_endpoint_and_query_budget(self):
        filters = validate_filters({**FORM, "keywords": "production engineer;manufacturing engineer", "country": "DE"}, [COMPANY])
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"jobs": []}).encode()
        with patch.dict("os.environ", {"JOOBLE_API_KEY_DE": "german-key", "WEB_MAX_MARKET_QUERIES": "1"}, clear=True), patch.object(requests, "post", return_value=response) as network:
            providers.jooble(filters)
        network.assert_called_once()
        self.assertEqual(network.call_args.args[0], "https://de.jooble.org/api/german-key")

    def test_excluding_intern_does_not_exclude_international_jobs(self):
        filters = validate_filters({**FORM, "keywords": "engineer"}, [COMPANY])
        jobs = [example_job(title="International Production Engineer"), example_job(title="Production Engineer Intern", link="https://example.org/intern")]
        with patch.dict(providers.COMPANY_PROVIDERS, {"smartrecruiters": lambda company, query: (jobs, [])}):
            result = providers.run_search(filters, [COMPANY])
        self.assertEqual([job["title"] for job in result["jobs"]], ["International Production Engineer"])


class WebTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "hunter.sqlite"
        self.app = create_app(self.path)
        self.app.testing = True
        self.client = self.app.test_client()
        page = self.client.get("/").get_data(as_text=True)
        self.csrf = re.search(r'name="hunter-csrf" content="([^"]+)"', page).group(1)
        self.headers = {"X-Hunter-CSRF": self.csrf}
        account = self.client.post('/api/auth/register', json={'name': 'Tester', 'email': 'tester@example.org', 'password': 'test-password-long'}, headers=self.headers)
        self.assertEqual(account.status_code, 201)
        self.user_id = account.json['user']['id']
        self.headers = {'X-Hunter-CSRF': account.json['csrf']}

    def tearDown(self):
        self.app.extensions["executor"].shutdown(wait=True)
        self.directory.cleanup()

    def search(self):
        result = {"jobs": [example_job()], "reports": [], "google_url": "https://google.com/", "coverage": "Test"}
        with patch.object(providers, "run_search", return_value=result):
            response = self.client.post("/api/search", json=FORM, headers=self.headers)
            self.assertEqual(response.status_code, 202)
            identifier = response.json["id"]
            self.app.extensions["executor"].shutdown(wait=True)
        self.assertEqual(self.client.get("/api/search/" + identifier).json["status"], "done")
        return identifier

    def test_csrf_and_foreign_origin_cannot_trigger_search(self):
        self.assertEqual(self.client.post("/api/search", json=FORM).status_code, 403)
        self.assertEqual(self.client.post("/api/search", json=FORM, headers={**self.headers, "Origin": "https://evil.example"}).status_code, 403)

    def test_config_exposes_readiness_without_credentials(self):
        with patch.dict("os.environ", {"JOOBLE_API_KEY": "SUPER_SECRET", "TELEGRAM_BOT_TOKEN": "ANOTHER_SECRET"}):
            response = self.client.get("/api/config")
        self.assertNotIn("SUPER_SECRET", response.get_data(as_text=True))
        self.assertNotIn("ANOTHER_SECRET", response.get_data(as_text=True))
        self.assertTrue(response.json["integrations"]["jooble"])
        self.assertEqual(len(self.client.get("/api/states/BR").json["states"]), 27)

    def test_results_favorites_and_history_survive_restart(self):
        identifier = self.search()
        job = self.client.get("/api/search/" + identifier).json["jobs"][0]
        self.assertEqual(self.client.post("/api/favorites", json={"id": job["id"], "search_id": identifier}, headers=self.headers).status_code, 200)
        reloaded = Store(self.path)
        self.assertEqual(reloaded.favorites(self.user_id)[0]["title"], "Production Engineer")
        self.assertEqual(reloaded.recent_searches(self.user_id)[0]["id"], identifier)
        self.assertEqual(self.client.delete("/api/favorites/" + job["id"], headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get("/api/favorites").json["jobs"], [])

    def test_company_registration_pause_and_duplicate_detection(self):
        company = {"name": "Example", "url": "https://jobs.lever.co/example", "provider": "lever", "identifier": "example"}
        with patch.object(providers, "discover_company", return_value=company):
            response = self.client.post("/api/companies", json=company, headers=self.headers)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(self.client.post("/api/companies", json=company, headers=self.headers).status_code, 409)
        identifier = response.json["id"]
        self.client.patch("/api/companies/" + str(identifier), json={"enabled": False}, headers=self.headers)
        registered = self.client.get("/api/config").json["companies"]
        self.assertEqual(next(item["enabled"] for item in registered if item["id"] == identifier), 0)

    def test_delivery_history_is_independent_per_channel_after_partial_failure(self):
        identifier = self.search()
        job = self.client.get("/api/search/" + identifier).json["jobs"][0]
        body = {"ids": [job["id"]], "search_id": identifier, "channels": ["telegram", "email"]}
        credentials = {"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_CHAT_ID": "123", "EMAIL_FROM": "fake@example.org", "EMAIL_TO": "target@example.org", "EMAIL_APP_PASSWORD": "fake"}
        with patch.dict("os.environ", credentials), patch.object(main, "send_telegram") as telegram, patch.object(main, "send_email", side_effect=RuntimeError("failure")) as email:
            first = self.client.post("/api/notify", json=body, headers=self.headers).json
            second = self.client.post("/api/notify", json=body, headers=self.headers).json
        self.assertEqual(first["reports"][0]["sent"], 1)
        self.assertEqual(second["reports"][0]["sent"], 0)
        self.assertEqual(email.call_count, 2)
        telegram.assert_called_once()
        self.assertTrue(self.app.extensions['store'].delivered(job['id'], 'telegram', self.user_id))
        self.assertFalse(self.app.extensions['store'].delivered(job['id'], 'email', self.user_id))

    def test_google_key_stays_local_and_is_never_echoed(self):
        key = "0123456789abcdef" * 4
        with patch("jobhunter.configuration.set_key") as save, patch.dict("os.environ", {}, clear=True):
            response = self.client.post("/api/integrations/google", json={"key": key}, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            save.assert_called_once()
            self.assertNotIn(key, self.client.get("/api/config").get_data(as_text=True))

    def test_jooble_key_registration_keeps_country_separate(self):
        key = "regional-german-key-for-tests"
        with patch("jobhunter.configuration.set_key") as save, patch.dict("os.environ", {}, clear=True):
            response = self.client.post("/api/integrations/jooble", json={"country": "DE", "key": key}, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(save.call_args.args[1], "JOOBLE_API_KEY_DE")
            config = self.client.get("/api/config")
            self.assertEqual(config.json["jooble_countries"], ["DE"])
            self.assertNotIn(key, config.get_data(as_text=True))

    def test_gemini_key_accepts_current_format_and_never_echoes_it(self):
        key = "AQ." + "fake_private_key_for_tests" * 2
        with patch("jobhunter.configuration.set_key") as save, patch.dict("os.environ", {}, clear=True):
            response = self.client.post("/api/integrations/gemini", json={"key": key}, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(save.call_args.args[1], "GEMINI_API_KEY")
            config = self.client.get("/api/config")
            self.assertTrue(config.json["integrations"]["gemini"])
            self.assertNotIn(key, config.get_data(as_text=True))
            self.assertEqual(len(config.json["jooble_markets"]), 66)

    def test_jooble_registration_does_not_offer_invented_country_domain(self):
        response = self.client.post("/api/integrations/jooble", json={"country": "CN", "key": "fake-key-with-enough-length"}, headers=self.headers)
        self.assertEqual(response.status_code, 400)

    def test_removing_all_companies_remains_empty_after_restart(self):
        for company in self.app.extensions['store'].companies(self.user_id):
            self.app.extensions['store'].update_company(company['id'], remove=True, user_id=self.user_id)
        self.assertEqual(Store(self.path).companies(self.user_id), [])


if __name__ == "__main__":
    unittest.main()
