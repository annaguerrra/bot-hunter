r"""QA opcional da interface local, com Edge em perfil temporário e fontes reais.

Uso: .venv\Scripts\python.exe scripts\check_ui.py
Requer web.py em execução. Não envia mensagens nem altera credenciais.
"""
import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "logs" / "qa"
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as runtime:
    browser = runtime.chromium.launch(channel="msedge", headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:5000", wait_until="networkidle")
    if page.locator('#auth-form').count():
        if not os.getenv('HUNTER_QA_EMAIL') or not os.getenv('HUNTER_QA_PASSWORD'):
            raise RuntimeError('Crie sua conta e defina HUNTER_QA_EMAIL/HUNTER_QA_PASSWORD para este teste autenticado. Para contas fictícias, use check_accounts_ui.py numa instância temporária.')
        if page.locator('.auth-card').get_attribute('data-first') == 'true':
            raise RuntimeError('Crie sua primeira conta na interface antes deste teste.')
        page.locator('#auth-email').fill(os.environ['HUNTER_QA_EMAIL'])
        page.locator('#auth-password').fill(os.environ['HUNTER_QA_PASSWORD'])
        page.locator('#auth-submit').click()
        expect(page.locator('#search-form')).to_be_visible(timeout=20000)
    expect(page.locator("#country option")).to_have_count(250)
    assert int(page.locator('#company-count').inner_text()) >= 5
    expect(page.locator("#salary-min")).to_have_value("7000")
    expect(page.locator("#profile")).to_have_value("both")
    page.screenshot(path=str(OUT / "desktop-home.png"), full_page=True)

    # Dependência região -> país -> estado, sem consumir uma busca.
    page.locator('#region-chips button[data-region="EU"]').click()
    expect(page.locator('#country option[value="BR"]')).to_have_count(0)
    page.locator("#country").select_option("DE")
    expect(page.locator("#state")).to_be_enabled()
    expect(page.locator('#state option[value="DE-BW"]')).to_have_count(1)
    page.locator("#state").select_option("DE-BW")
    page.locator("#reset-filters").click()
    expect(page.locator("#state")).to_be_disabled()
    expect(page.locator("#region")).to_have_value("")

    # Busca real internacional: uma página na fonte pública da Bosch.
    page.locator("#search-button").click()
    expect(page.locator("#search-button")).to_be_enabled(timeout=180000)
    expect(page.locator("#results-title")).to_have_text(re.compile(r"\d+ vagas com salário aprovado · \d+ para análise"))
    eligible_count = page.locator("#jobs-list .job-card").count()
    page.locator('[data-salary-view="review"]').click()
    count = page.locator("#jobs-list .job-card").count()
    assert count > 0, "A busca internacional na Bosch não retornou vagas para análise."
    expect(page.locator("#jobs-list [data-job-select]")).to_have_count(0)
    page.screenshot(path=str(OUT / "desktop-results.png"), full_page=True)
    titles = page.locator("#jobs-list .job-title").all_text_contents()
    countries = page.locator("#jobs-list .tag:not(.source)").all_text_contents()

    # Detalhes, favoritas persistentes e seleção/envio (sem enviar).
    page.locator("#jobs-list [data-job-detail]").first.click()
    expect(page.locator("#job-dialog")).to_be_visible()
    page.locator('[data-close="job-dialog"]').click()
    first_save = page.locator("#jobs-list [data-job-save]").first
    was_saved = first_save.get_attribute("aria-pressed") == "true"
    if not was_saved:
        first_save.click()
        expect(first_save).to_have_attribute("aria-pressed", "true")
    page.locator('a.nav-link[data-view="favorites"]').click()
    expect(page.locator("#favorites-list .job-card").first).to_be_visible()
    page.locator('a.nav-link[data-view="explore"]').click()
    if not was_saved:
        page.locator("#jobs-list [data-job-save]").first.click()
        expect(page.locator("#jobs-list [data-job-save]").first).to_have_attribute("aria-pressed", "false")
    # Vagas sem salário podem ser salvas, mas não selecionadas para alertas.

    page.locator('a.nav-link[data-view="companies"]').click()
    expect(page.locator("#companies-list")).to_contain_text("Bosch")
    page.screenshot(path=str(OUT / "desktop-companies.png"), full_page=True)
    page.locator('a.nav-link[data-view="integrations"]').click()
    expect(page.locator("#google-form")).to_be_visible()
    expect(page.locator("#jooble-form")).to_be_visible()
    expect(page.locator("#gemini-form")).to_be_visible()
    expect(page.locator("#jooble-country option")).to_have_count(66)
    expect(page.locator("#jooble-checklist .market-row")).to_have_count(66)
    expect(page.locator('#jooble-country option[value="CN"]')).to_have_count(0)
    page.locator('[data-jooble-market="US"]').click()
    expect(page.locator("#jooble-country")).to_have_value("US")
    expect(page.locator("#jooble-signup-link")).to_have_attribute("href", "https://jooble.org/api/about")
    page.locator("#jooble-country").select_option("BR")
    page.locator("#gemini-form").scroll_into_view_if_needed()
    expect(page.locator("#jooble-country")).to_have_value("BR")
    page.locator("#jooble-country").select_option("DE")
    expect(page.locator("#jooble-signup-link")).to_have_attribute("href", "https://de.jooble.org/api/about")
    page.locator("#jooble-country").select_option("BR")
    page.screenshot(path=str(OUT / "desktop-integrations.png"), full_page=True)
    page.locator('a.nav-link[data-view="history"]').click()
    expect(page.locator("#history-list .history-row").first).to_be_visible()
    page.locator("#history-list [data-history-open]").first.click()
    expect(page.locator("#view-explore")).to_be_visible()
    page.locator('[data-salary-view="review"]').click()
    expect(page.locator("#jobs-list .job-card")).to_have_count(count)

    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(OUT / "mobile-results.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "A interface mobile tem rolagem horizontal."
    assert not errors, errors
    summary = {"eligible_jobs": eligible_count, "review_jobs": count, "countries": sorted(set(countries)), "sample_titles": titles[:5], "browser_errors": errors,
               "checks": ["7000 BRL floor", "product/production profile", "region/country/state", "global live search", "details", "favorites", "unknown salary cannot alert", "companies", "Gemini form", "66 Jooble registration links", "history", "mobile layout"]}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    context.close()
    browser.close()
