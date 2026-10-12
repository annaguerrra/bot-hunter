"""Casos reais de títulos e regras de salário mínimo, sem rede."""
import unittest
from unittest.mock import patch
import requests
from jobhunter import matching, salary

def job(title="Product Engineer", pay="R$ 8.000 mensal", path="1", **extra):
    return {"id": path, "title": title, "company": "Bosch", "location": "Curitiba, Brasil",
            "link": "https://jobs.example.org/" + path, "country": "BR", "salary": pay, **extra}

class MatchingTests(unittest.TestCase):
    def test_user_reported_unrelated_titles_are_all_rejected(self):
        titles = ["Coordenador comercial - PR", "Coordenador Administrativo - PR", "Coordenador de Cozinha - PR",
                  "Coordenadora de RH - PR", "Coordenador Fiscal de escritório de contabilidade - PR",
                  "Coordenador de importação - PR", "COORDENADOR DE EQUIPE DE VENDAS EXTERNAS",
                  "Coordenador De Obras - Engenheiro Civil - Incorporadora/Construtora/FB",
                  "COORDENADOR(A) DE PLATAFORMA IMOBILIÁRIA", "COORDENADOR DE EMPREGABILIDADE",
                  "Coordenador(a) de produção de eventos corporativos"]
        for title in titles:
            with self.subTest(title=title):
                self.assertFalse(matching.assess(job(title))["matched"])
        self.assertTrue(matching.assess(job("Coordenador de Produção Industrial"))["matched"])

    def test_product_and_production_language_case_gender_and_plural(self):
        titles = ["ENGENHEIRA DE PRODUTOS", "Eng. de Produto", "Senior Product Development Engineer (m/f/d)",
                  "Ingeniera de Producto", "Produktentwickler (w/m/d)", "Konstruktionsingenieur",
                  "Ingénieur produit", "Ingegnere di prodotto", "产品工程师", "製品開発", "제품 개발 엔지니어",
                  "Product Design Engineer", "Engenheiro(a) do Produto", "Engenheiros de Produção",
                  "Manufacturing Engineer", "Fertigungsingenieur", "Ingeniero de producción", "生産技術"]
        for title in titles:
            with self.subTest(title=title):
                self.assertTrue(matching.assess(job(title))["matched"])

    def test_product_and_production_profiles_are_distinct(self):
        self.assertFalse(matching.assess(job("Manufacturing Engineer"), "product")["matched"])
        self.assertTrue(matching.assess(job("Product Engineer"), "product")["matched"])
        self.assertFalse(matching.assess(job("Product Engineer"), "production")["matched"])

    def test_software_is_not_physical_product_and_intern_not_international(self):
        self.assertFalse(matching.assess(job("Product Software Engineer"))["matched"])
        self.assertFalse(matching.assess(job(description="Build our SaaS web application frontend"))["matched"])
        self.assertTrue(matching.assess(job("International Product Engineer"), excluded=["intern"])["matched"])
        self.assertFalse(matching.assess(job("Product Engineer Intern"), excluded=["intern"])["matched"])

    def test_local_language_and_original_term_are_in_bounded_query_plan(self):
        queries = matching.expand_queries(["Senior Product Design Engineer"], "both", "DE")
        self.assertIn("Produktentwickler", queries)
        self.assertIn("Produktionsingenieur", queries)
        self.assertIn("Senior Product Design Engineer", queries)
        self.assertIn("product engineer", queries)
        self.assertLessEqual(len(queries), 24)
        self.assertEqual(matching.expand_queries(["designer"], "custom", "DE"), ["designer"])


class SalaryTests(unittest.TestCase):
    def test_brazilian_ranges_minimum_and_numeric_formats(self):
        for pay, status, amount in [("R$ 2.600 mensal", "below", 2600), ("R$ 7.000 por mês", "eligible", 7000),
                                    ("R$ 8.000 a R$ 9.000 mensal", "eligible", 8000), ("BRL 6,000-9,000 per month", "below", 6000),
                                    ("R$ 7.500,50 mensal", "eligible", 7500.50), ("BRL 8k monthly", "eligible", 8000)]:
            with self.subTest(pay=pay):
                result = salary.evaluate(job(pay=pay))
                self.assertEqual(result["status"], status)
                self.assertEqual(result["monthly_brl"], amount)

    def test_unknown_ambiguous_estimated_and_upper_bound_go_to_review(self):
        for pay in ["", "a combinar", "R$ 8.000", "$ 8,000 monthly", "até R$ 9.000 mensal", "estimated USD 100000 yearly"]:
            with self.subTest(pay=pay):
                self.assertEqual(salary.evaluate(job(pay=pay))["status"], "review")

    def test_annual_salary_converts_monthly_with_published_exchange_date(self):
        fetch = lambda currency: (5.0, "2026-10-09")
        result = salary.evaluate(job(pay="USD 24,000-30,000 per year"), rate_fetch=fetch)
        self.assertEqual(result["monthly_brl"], 10000)
        self.assertEqual(result["rate_date"], "2026-10-09")
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(salary.evaluate(job(pay="EUR 12k per year"), rate_fetch=lambda currency: (6, "2026-10-09"))["status"], "below")

    def test_hourly_rate_needs_hours_not_assumed_full_time(self):
        data = {"min": 20, "currency": "USD", "period": "HOUR"}
        self.assertEqual(salary.evaluate(job(pay="", salary_data=data))["status"], "review")
        result = salary.evaluate(job(pay="", salary_data={**data, "hours_per_week": 40}), rate_fetch=lambda currency: (5, "2026-10-09"))
        self.assertEqual(result["status"], "eligible")

    def test_local_salary_periods_and_suffixes(self):
        for pay, amount in [("EUR 60.000 jährlich", 5000), ("EUR 3.500 mensile", 3500),
                            ("EUR 40 000 annuel", 40000 / 12), ("INR 12 LPA", 100000), ("年薪 CNY 30万", 25000)]:
            with self.subTest(pay=pay):
                result = salary.evaluate(job(pay=pay), rate_fetch=lambda currency: (1, "2026-10-09"))
                self.assertEqual(result["monthly_brl"], round(amount, 2))

    def test_country_inferred_from_query_does_not_determine_ambiguous_dollar(self):
        candidate = job(pay="$ 8,000 per month") | {"country": "US", "country_basis": "consulta"}
        self.assertEqual(salary.evaluate(candidate)["status"], "review")

    def test_fx_failure_never_approves_and_nonfinite_input_never_approves(self):
        with patch.object(salary.requests, "get", side_effect=requests.Timeout):
            self.assertEqual(salary.evaluate(job(pay="CHF 8000 monthly"))["status"], "review")
        self.assertEqual(salary.evaluate(job(pay="", salary_data={"min": "nan", "period": "MONTH", "currency": "BRL"}))["status"], "review")


if __name__ == "__main__":
    unittest.main()
