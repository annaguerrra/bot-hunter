"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = { config: null, jobs: [], favorites: [], selected: new Set(), searchId: "", history: [], searching: false, salaryView: "eligible" };
const money = (value) => Number(value).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
let csrf = $('meta[name="hunter-csrf"]').content;
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const countryName = (code) => state.config.countries.find((country) => country.code === code)?.name || "Mundo todo";
const regionName = (code) => state.config.regions.find((region) => region.code === code)?.name || "Mundo todo";
const providerName = (provider) => ({ smartrecruiters: "SmartRecruiters", greenhouse: "Greenhouse", greenhouse_eu: "Greenhouse Europa", lever: "Lever", lever_eu: "Lever Europa", website: "Página pública · compatibilidade variável" }[provider] || provider);
let toastTimer;

function toast(message, error = false) {
  const target = $("#toast");
  target.textContent = message;
  target.className = `toast${error ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => target.classList.add("hidden"), 6500);
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", "X-Hunter-CSRF": csrf, ...options.headers } });
  const body = await response.json().catch(() => ({ error: "Não foi possível ler a resposta da aplicação." }));
  if (response.status === 401 && !path.startsWith('/api/auth/')) { location.replace('/'); }
  if (!response.ok) throw new Error(body.error || "Não foi possível completar esta ação.");
  return body;
}

function empty(title, message, name = "search") {
  return `<div class="empty-state"><div class="empty-icon">${icon(name)}</div><h3>${esc(title)}</h3><p>${esc(message)}</p></div>`;
}

function setRegion(value) {
  $("#region").value = value;
  renderCountries();
  $("#country").value = "";
  resetStates();
  $$(".region-chips .chip").forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.region === value);
    chip.setAttribute("aria-pressed", String(chip.dataset.region === value));
  });
  updateGoogleLink();
}

function renderCountries() {
  const region = $("#region").value;
  const options = state.config.countries.filter((country) => !region || country.region === region);
  $("#country").innerHTML = '<option value="">Todos os países</option>' + options.map((country) => `<option value="${esc(country.code)}">${esc(country.name)}</option>`).join("");
}

function resetStates() {
  $("#state").innerHTML = '<option value="">Selecione um país primeiro</option>';
  $("#state").disabled = true;
}

async function loadStates(selected = "") {
  const country = $("#country").value;
  if (!country) { resetStates(); updateGoogleLink(); return; }
  $("#state").disabled = true;
  const body = await api(`/api/states/${encodeURIComponent(country)}`);
  if ($("#country").value !== country) return;
  $("#state").innerHTML = '<option value="">Todos os estados / províncias</option>' + body.states.map((item) => `<option value="${esc(item.code)}">${esc(item.name)}</option>`).join("");
  $("#state").disabled = !body.states.length;
  $("#state").value = selected;
  updateGoogleLink();
}

function filters() {
  return { keywords: $("#keywords").value, region: $("#region").value, country: $("#country").value,
    state: $("#state").value, city: $("#city").value, sources: $$('input[name="source"]:checked').map((input) => input.value),
    company_ids: state.config.companies.filter((company) => company.enabled).map((company) => company.id),
    strict_title: $("#strict-title").checked, remote: $("#remote-only").checked,
    excluded: $("#excluded").value, pages: Number($("#pages").value), profile: $("#profile").value,
    salary_min: Number($("#salary-min").value), multilingual: $("#multilingual").checked };
}

function updateGoogleLink() {
  const where = [$("#city").value, $("#state").selectedOptions[0]?.textContent, $("#country").value ? countryName($("#country").value) : regionName($("#region").value)]
    .filter((value) => value && !/Selecione|Todos os/.test(value)).join(" ");
  const query = ($("#keywords").value.trim() || "production engineer").split(";").join(" OR ") + " jobs " + where;
  $("#google-link").href = "https://www.google.com/search?" + new URLSearchParams({ q: query, udm: "8" });
}

async function refreshConfig() {
  state.config = await api("/api/config");
  $('#workspace-name').textContent = state.config.user.name;
  $$('[data-user-initial]').forEach((item) => item.textContent = state.config.user.name.slice(0, 1).toUpperCase());
  $('#google-form').closest('.google-connect').classList.toggle('hidden', state.config.user.role !== 'admin');
  $('#jooble-guide').dataset.admin = String(state.config.user.role === 'admin');
  $("#company-count").textContent = state.config.companies.length;
  ["google", "jooble", "gemini"].forEach((name) => $("#" + name + "-status").className = "source-dot " + (state.config.integrations[name] ? "ready" : "pending"));
  $("#google-setup-hint").classList.toggle("hidden", state.config.integrations.google);
  const previousJoobleCountry = $("#jooble-country").value || "BR";
  $("#jooble-country").innerHTML = state.config.jooble_markets.map((country) => `<option value="${esc(country.code)}">${esc(country.name)}</option>`).join("");
  $("#jooble-country").value = previousJoobleCountry;
  $("#jooble-markets").textContent = "Países configurados: " + (state.config.jooble_countries.map(countryName).join(", ") || "nenhum ainda");
  $("#jooble-checklist").innerHTML = `<p>${state.config.jooble_countries.filter((code) => state.config.jooble_markets.some((market) => market.code === code)).length} de ${state.config.jooble_markets.length} mercados cadastrados. Cada solicitação depende da aprovação da Jooble.</p><div class="market-list">${state.config.jooble_markets.map((market) => `<div class="market-row"><span>${state.config.jooble_countries.includes(market.code) ? "✓" : "○"} ${esc(market.name)} <small>${esc(market.code)}</small></span><a href="${esc(market.signup_url)}" target="_blank" rel="noopener noreferrer">Solicitar chave ↗</a><button type="button" class="text-button" data-jooble-market="${esc(market.code)}">Cadastrar</button></div>`).join("")}</div>`;
  updateJoobleSignup();
  renderCompanies();
  renderIntegrations();
}

function renderCompanies() {
  const companies = state.config.companies;
  $("#companies-list").innerHTML = companies.length ? companies.map((company) => `<article class="company-card"><div class="company-card-top"><span class="company-monogram">${esc(company.name.slice(0, 2).toUpperCase())}</span><div><h3>${esc(company.name)}</h3><a href="${esc(company.url)}" target="_blank" rel="noopener noreferrer">${esc(company.url)} ${icon("external")}</a></div></div><div class="company-card-bottom"><span class="tag source">${esc(providerName(company.provider))}</span><label class="toggle-label"><input type="checkbox" data-company-toggle="${company.id}" ${company.enabled ? "checked" : ""}>${company.enabled ? "No radar" : "Pausada"}</label><button class="icon-button" data-company-remove="${company.id}" aria-label="Remover ${esc(company.name)}">${icon("trash")}</button></div></article>`).join("") : empty("Seu radar de empresas está vazio.", "Adicione uma página de carreiras para começar.", "building");
}

function renderIntegrations() {
  const descriptions = {
    jooble: ["Jooble", "Buscas por cargo nos países com chave configurada. Cada país exige sua própria chave.", "globe"],
    google: ["Google Empregos", "Importe resultados da interface de empregos do Google usando SerpAPI.", "search"],
    gemini: ["Gemini + Google Search", "Pesquisa multilíngue com fontes e avaliação de compatibilidade das vagas.", "search"],
    telegram: ["Telegram", "Envie as oportunidades selecionadas para o chat configurado no seu bot.", "send"],
    email: ["E-mail", "Receba um resumo com os links das vagas no seu e-mail configurado.", "briefcase"]
  };
  $("#integration-cards").innerHTML = Object.entries(descriptions).map(([key, [name, description, symbol]]) => `<article class="integration-card"><span class="form-icon">${icon(symbol)}</span><div><h2>${name}</h2><span class="integration-status${state.config.integrations[key] ? "" : " pending"}">${state.config.integrations[key] ? "Configurado" : "Aguardando configuração"}</span><p>${description}</p></div></article>`).join("");
  ["telegram", "email"].forEach((channel) => {
    const input = $("#notify-" + channel);
    input.disabled = !state.config.integrations[channel];
    input.checked = state.config.integrations[channel];
  });
}

function jobCard(job, savedView = false) {
  const saved = state.favorites.some((favorite) => favorite.id === job.id);
  const location = job.location || job.country_name || "Localização não informada";
  const date = job.updated ? new Date(job.updated).toLocaleDateString("pt-BR") : job.posted_label || "";
  const check = job.salary_check;
  const eligible = check?.status === "eligible";
  const salaryLabel = eligible ? `${money(check.monthly_brl)}/mês · piso equivalente` : "Para análise · salário não confirmado";
  const evaluation = job.ai_assessment ? `Gemini: ${job.ai_assessment.score}/100 · ${job.ai_assessment.reason}` : job.match?.reason || "";
  return `<article class="job-card"><div class="job-top"><span class="company-monogram">${esc((job.company || "?").slice(0, 2).toUpperCase())}</span><div class="job-title-wrap"><h3 class="job-title"><button data-job-detail="${job.id}">${esc(job.title)}</button></h3><div class="job-company">${esc(job.company || "Empresa não informada")}</div></div><button class="job-save${saved ? " saved" : ""}" data-job-save="${job.id}" aria-label="${saved ? "Remover vaga salva" : "Salvar vaga"}" aria-pressed="${saved}">${icon("heart")}</button></div><div class="job-meta"><span>${icon("pin")}${esc(location)}</span>${job.employment ? `<span>${icon("briefcase")}${esc(job.employment)}</span>` : ""}${job.salary ? `<span>${esc(job.salary)}</span>` : ""}</div><p class="salary-verdict${eligible ? "" : " pending"}">${esc(salaryLabel)}</p><p class="field-help">${esc(evaluation)}</p><div class="job-tags">${job.country_name ? `<span class="tag">${esc(job.country_name)}${job.country_basis === "consulta" ? " · país da busca" : ""}</span>` : ""}${job.remote ? '<span class="tag">Remoto</span>' : ""}${job.sources.map((source) => `<span class="tag source">${esc(source)}</span>`).join("")}</div><div class="job-bottom">${savedView || !eligible ? `<span class="job-date">${esc(date)}</span>` : `<label class="checkbox-label job-select"><input type="checkbox" data-job-select="${job.id}" ${state.selected.has(job.id) ? "checked" : ""}>Selecionar para alerta</label>`}<a class="job-apply" href="${esc(job.link)}" target="_blank" rel="noopener noreferrer">Ver oportunidade ${icon("external")}</a></div></article>`;
}

function renderJobs() {
  const jobs = state.jobs.filter((job) => (job.salary_check?.status === "eligible" ? "eligible" : "review") === state.salaryView);
  const order = $("#sort-results").value;
  if (order === "company") jobs.sort((a, b) => a.company.localeCompare(b.company));
  if (order === "country") jobs.sort((a, b) => a.country_name.localeCompare(b.country_name));
  if (order === "newest") jobs.sort((a, b) => (b.updated || "").localeCompare(a.updated || ""));
  if (order === "relevance") jobs.sort((a, b) => (b.ai_assessment?.score ?? b.match?.score ?? 0) - (a.ai_assessment?.score ?? a.match?.score ?? 0));
  $("#jobs-list").innerHTML = jobs.length ? jobs.map((job) => jobCard(job)).join("") : empty(state.salaryView === "eligible" ? "Nenhuma vaga com salário mínimo confirmado." : "Nenhuma vaga pendente de análise.", "Consulte a lista Para análise, amplie o destino ou conecte outras fontes. Salários abaixo do mínimo e cargos de outra área são excluídos.", "globe");
  updateSelection();
}

function renderReports(reports = []) {
  $("#source-reports").innerHTML = reports.map((report) => {
    const summary = report.status === "ok" ? `${report.matched} com salário aprovado · ${report.review || 0} para análise · ${report.below_minimum || 0} abaixo do piso · ${report.received} recebidas` : report.status === "pending" ? "Configuração pendente" : "Falha na consulta";
    const notes = (report.notes || []).map((note) => `<p>${esc(note)}</p>`).join("");
    const queries = report.queries?.length ? `<p><strong>Termos consultados:</strong> ${report.queries.map(esc).join(" · ")}</p>` : "";
    return `<div class="source-report${report.status === "pending" ? " warning" : report.status === "error" ? " error" : ""}"><strong>${esc(report.name)} · ${summary}</strong>${notes || queries ? `<details${report.status !== "ok" ? " open" : ""}><summary>Detalhes da fonte e cobertura</summary>${notes}${queries}</details>` : ""}</div>`;
  }).join("");
}

function showSearchResult(result) {
  state.searchId = result.id;
  state.jobs = [...(result.jobs || []), ...(result.review_jobs || [])];
  state.salaryView = "eligible";
  state.selected.clear();
  const eligible = state.jobs.filter((job) => job.salary_check?.status === "eligible").length;
  const review = state.jobs.length - eligible;
  $("#results-title").textContent = `${eligible} vagas com salário aprovado · ${review} para análise`;
  $("#salary-tabs").classList.remove("hidden");
  $("[data-salary-view=eligible]").textContent = `Salário aprovado (${eligible})`;
  $("[data-salary-view=review]").textContent = `Para análise (${review})`;
  $$('[data-salary-view]').forEach((button) => button.classList.toggle("active", button.dataset.salaryView === "eligible"));
  $("#research-sources").innerHTML = result.research_sources?.length ? `<details class="source-report"><summary>Fontes da pesquisa Gemini (${result.research_sources.length})</summary>${result.research_sources.map((source) => `<p><a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.title)}</a></p>`).join("")}</details>` : "";
  if (result.search_suggestions) $("#research-sources").insertAdjacentHTML("beforeend", `<iframe class="search-suggestions" title="Sugestões de pesquisa do Google" sandbox="allow-popups allow-popups-to-escape-sandbox" src="/api/search/${encodeURIComponent(result.id)}/grounding"></iframe>`);
  const destination = result.filters.country ? countryName(result.filters.country) : regionName(result.filters.region);
  $("#results-subtitle").textContent = `${destination} · ${result.filters.keywords.join(" / ")} · resultados desta busca`;
  renderReports(result.reports);
  if (result.google_url) $("#google-link").href = result.google_url;
  $("#coverage-note").textContent = result.coverage || "Resultados das fontes consultadas.";
  renderJobs();
}

function setSearching(value) {
  state.searching = value;
  $("#search-button").disabled = value;
  $("#search-button span").textContent = value ? "Explorando oportunidades…" : "Encontrar oportunidades";
  $("#search-progress").classList.toggle("hidden", !value);
}

async function pollSearch(identifier, started = Date.now()) {
  try {
    const result = await api(`/api/search/${identifier}`);
    if (result.status === "running") {
      if (Date.now() - started > 600000) throw new Error("A busca continua no servidor. Consulte o histórico em alguns instantes.");
      setTimeout(() => pollSearch(identifier, started), 1000);
      return;
    }
    if (result.status !== "done") throw new Error(result.error || "A busca foi interrompida. Tente novamente.");
    showSearchResult(result);
    setSearching(false);
    await loadHistory();
    toast(`${state.jobs.length} oportunidades encontradas. Seu radar foi atualizado.`);
  } catch (error) {
    setSearching(false);
    toast(error.message, true);
  }
}

async function startSearch() {
  if (state.searching) return;
  setSearching(true);
  try {
    const result = await api("/api/search", { method: "POST", body: JSON.stringify(filters()) });
    state.searchId = result.id;
    await pollSearch(result.id);
  } catch (error) {
    setSearching(false);
    toast(error.message, true);
  }
}

function updateSelection() {
  $("#selection-bar").classList.toggle("hidden", !state.selected.size);
  $("#selection-count").textContent = `${state.selected.size} selecionada${state.selected.size === 1 ? "" : "s"}`;
}

async function loadFavorites() {
  state.favorites = (await api("/api/favorites")).jobs;
  $("#favorite-count").textContent = state.favorites.length;
  $("#favorites-list").innerHTML = state.favorites.length ? state.favorites.map((job) => jobCard(job, true)).join("") : empty("Guarde as oportunidades que combinam com você.", "Clique no coração de uma vaga para encontrá-la aqui depois.", "heart");
}

async function toggleFavorite(identifier) {
  const job = [...state.jobs, ...state.favorites].find((item) => item.id === identifier);
  if (!job) return;
  const saved = state.favorites.some((favorite) => favorite.id === identifier);
  await api(saved ? `/api/favorites/${identifier}` : "/api/favorites", { method: saved ? "DELETE" : "POST", body: saved ? undefined : JSON.stringify({ id: identifier, search_id: state.searchId }) });
  await loadFavorites();
  if (state.searchId) renderJobs();
  toast(saved ? "Vaga removida das salvas." : "Oportunidade salva para olhar depois.");
}

function jobDetail(identifier) {
  const job = [...state.jobs, ...state.favorites].find((item) => item.id === identifier);
  if (!job) return;
  $("#job-detail").innerHTML = `<h2 class="detail-title">${esc(job.title)}</h2><p class="detail-company">${esc(job.company)} · ${esc(job.location)}</p><div class="job-tags">${job.sources.map((source) => `<span class="tag source">${esc(source)}</span>`).join("")}</div><p class="salary-verdict">${esc(job.salary_check?.reason || "Salário não verificado")}${job.salary_check?.monthly_brl ? " · " + money(job.salary_check.monthly_brl) + "/mês" : ""}</p><p class="field-help">${esc(job.salary || "Salário não informado")}${job.salary_check?.currency && job.salary_check.currency !== "BRL" ? " · Cotação " + esc(job.salary_check.rate_date || "pendente") + " · " + esc(job.salary_check.rate_source || "") : ""}</p><p class="field-help">${esc(job.ai_assessment?.reason || job.match?.reason || "")}</p><div class="detail-description">${esc(job.description || "A fonte fornece o título e a localização desta oportunidade. Abra o anúncio original para ver a descrição completa e se candidatar.")}</div><a class="button primary" href="${esc(job.link)}" target="_blank" rel="noopener noreferrer">Abrir anúncio original ${icon("external")}</a>`;
  $("#job-dialog").showModal();
}

async function loadHistory() {
  state.history = (await api("/api/searches")).searches;
  $("#history-list").innerHTML = state.history.length ? state.history.map((item) => `<article class="history-row"><span class="form-icon">${icon("clock")}</span><div><h3>${esc(item.filters.keywords.join(" / "))}</h3><p>${esc(item.filters.country ? countryName(item.filters.country) : regionName(item.filters.region))} · ${new Date(item.created_at).toLocaleString("pt-BR")} · ${{ done: "Concluída", running: "Em andamento", interrupted: "Interrompida", error: "Falha" }[item.status]}</p></div><div class="history-actions"><button class="button" data-history-open="${item.id}">Ver resultados</button><button class="button" data-history-repeat="${item.id}">Usar filtros ${icon("arrow")}</button></div></article>`).join("") : empty("Cada busca abre um novo caminho.", "As suas buscas aparecerão aqui para você retomar quando quiser.", "clock");
}

async function restoreFilters(saved) {
  setRegion(saved.region);
  $("#country").value = saved.country;
  await loadStates(saved.state);
  $("#keywords").value = saved.keywords.join(";");
  $("#city").value = saved.city;
  $("#strict-title").checked = saved.strict_title;
  $("#remote-only").checked = saved.remote;
  $("#excluded").value = saved.excluded.join(";");
  $("#pages").value = String(saved.pages);
  $("#profile").value = saved.profile || "both";
  $("#salary-min").value = saved.salary_min ?? 7000;
  updateSalaryFloor();
  $("#multilingual").checked = saved.multilingual !== false;
  $$('input[name="source"]').forEach((input) => input.checked = saved.sources.includes(input.value));
  updateGoogleLink();
}

async function navigate() {
  let view = location.hash.slice(1) || "explore";
  if (!["explore", "companies", "favorites", "history", "integrations", "profile"].includes(view)) view = "explore";
  $$(".view").forEach((section) => section.classList.toggle("hidden", section.id !== `view-${view}`));
  $("#jooble-settings").classList.toggle("hidden", view !== "integrations" || state.config.user.role !== 'admin');
  $("#gemini-settings").classList.toggle("hidden", view !== "integrations" || state.config.user.role !== 'admin');
  $("#jooble-guide").classList.toggle("hidden", view !== "integrations");
  $("#gemini-billing-note").classList.toggle("hidden", view !== "integrations");
  $$(".nav-link").forEach((link) => link.classList.toggle("active", link.dataset.view === view));
  $("#page-name").textContent = { explore: "Explorar vagas", companies: "Empresas", favorites: "Vagas salvas", history: "Histórico", integrations: "Integrações", profile: 'Meu perfil' }[view];
  if (view === "favorites") await loadFavorites();
  if (view === "history") await loadHistory();
  if (view === 'profile') await loadProfile();
}

async function guarded(action) {
  try { await action(); } catch (error) { toast(error.message, true); }
}

$("#region").addEventListener("change", () => setRegion($("#region").value));
$("#country").addEventListener("change", () => guarded(() => loadStates()));
["#state", "#city", "#keywords"].forEach((selector) => $(selector).addEventListener("change", updateGoogleLink));
$("#region-chips").addEventListener("click", (event) => {
  const chip = event.target.closest("[data-region]");
  if (chip) setRegion(chip.dataset.region);
});
$("#search-form").addEventListener("submit", (event) => { event.preventDefault(); startSearch(); });
$("#salary-tabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-salary-view]");
  if (!button) return;
  state.salaryView = button.dataset.salaryView;
  $$('[data-salary-view]').forEach((item) => item.classList.toggle("active", item === button));
  renderJobs();
});
$("#gemini-form").addEventListener("submit", (event) => {
  event.preventDefault();
  guarded(async () => {
    const button = $("#gemini-form button");
    button.disabled = true;
    try {
      await api("/api/integrations/gemini", { method: "POST", body: JSON.stringify({ key: $("#gemini-key").value }) });
      $("#gemini-key").value = "";
      await refreshConfig();
      toast("Gemini configurado. Selecione Gemini + Google Search na próxima busca.");
    } finally { button.disabled = false; }
  });
});
$("#reset-filters").addEventListener("click", () => { $("#search-form").reset(); $("#keywords").value = state.config.defaults.keywords; setRegion(""); toast("Filtros restaurados."); });
$("#sort-results").addEventListener("change", renderJobs);
$("#clear-selection").addEventListener("click", () => { state.selected.clear(); renderJobs(); });
$("#notify-open").addEventListener("click", () => {
  if (state.selected.size > 15) { toast("Selecione até 15 vagas por envio.", true); return; }
  $("#notify-dialog").showModal();
});
$("#notify-form").addEventListener("submit", (event) => {
  event.preventDefault();
  guarded(async () => {
    const button = $("#notify-form button");
    button.disabled = true;
    try {
      const result = await api("/api/notify", { method: "POST", body: JSON.stringify({ ids: [...state.selected], search_id: state.searchId, channels: $$('input[name="channel"]:checked').map((input) => input.value) }) });
      toast(result.reports.map((report) => `${report.channel === "email" ? "E-mail" : "Telegram"}: ${report.status === "ok" ? report.sent + " vagas enviadas" : report.note}`).join(" · "), result.reports.some((report) => report.status === "error"));
      $("#notify-dialog").close();
    } finally { button.disabled = false; }
  });
});
$("#company-form").addEventListener("submit", (event) => {
  event.preventDefault();
  guarded(async () => {
    const button = $("#company-form button");
    button.disabled = true;
    try {
      const company = await api("/api/companies", { method: "POST", body: JSON.stringify({ name: $("#company-name").value, url: $("#company-url").value }) });
      await refreshConfig();
      $("#company-form").reset();
      toast(`${company.name} está no seu radar. Fonte: ${providerName(company.provider)}.`);
    } finally { button.disabled = false; }
  });
});
$("#google-form").addEventListener("submit", (event) => {
  event.preventDefault();
  guarded(async () => {
    const button = $("#google-form button");
    button.disabled = true;
    try {
      await api("/api/integrations/google", { method: "POST", body: JSON.stringify({ key: $("#serpapi-key").value }) });
      $("#serpapi-key").value = "";
      await refreshConfig();
      toast("Chave salva. Selecione Google Empregos na próxima busca.");
    } finally { button.disabled = false; }
  });
});
document.addEventListener("click", (event) => {
  const element = event.target.closest("[data-job-save], [data-job-detail], [data-company-remove], [data-history-open], [data-history-repeat], [data-close]");
  if (!element) return;
  guarded(async () => {
    if (element.dataset.close) $("#" + element.dataset.close).close();
    if (element.dataset.jobSave) await toggleFavorite(element.dataset.jobSave);
    if (element.dataset.jobDetail) jobDetail(element.dataset.jobDetail);
    if (element.dataset.companyRemove) {
      const company = state.config.companies.find((item) => item.id === Number(element.dataset.companyRemove));
      if (!confirm(`Remover ${company.name} do seu radar?`)) return;
      await api(`/api/companies/${company.id}`, { method: "DELETE" });
      await refreshConfig();
      toast("Empresa removida do radar.");
    }
    if (element.dataset.historyOpen) {
      const result = await api(`/api/search/${element.dataset.historyOpen}`);
      if (result.status === "running") { toast("Esta busca ainda está em andamento."); return; }
      if (result.status !== "done") throw new Error(result.error || "Esta busca foi interrompida. Use os filtros para tentar novamente.");
      showSearchResult(result);
      location.hash = "explore";
    }
    if (element.dataset.historyRepeat) {
      const item = state.history.find((entry) => entry.id === element.dataset.historyRepeat);
      await restoreFilters(item.filters);
      location.hash = "explore";
      toast("Filtros recuperados. Clique em Encontrar oportunidades para atualizar a busca.");
    }
  });
});
document.addEventListener("change", (event) => {
  const element = event.target;
  if (element.dataset.jobSelect) {
    if (element.checked) state.selected.add(element.dataset.jobSelect); else state.selected.delete(element.dataset.jobSelect);
    updateSelection();
  }
  if (element.dataset.companyToggle) guarded(async () => {
    await api(`/api/companies/${element.dataset.companyToggle}`, { method: "PATCH", body: JSON.stringify({ enabled: element.checked }) });
    await refreshConfig();
  });
});
window.addEventListener("hashchange", () => guarded(navigate));

function updateJoobleSignup() {
  const code = $("#jooble-country").value;
  const market = state.config.jooble_markets.find((item) => item.code === code);
  $("#jooble-signup-link").href = market?.signup_url || "https://jooble.org/api/about";
}
$("#jooble-checklist").addEventListener("click", (event) => {
  const button = event.target.closest("[data-jooble-market]");
  if (!button) return;
  $("#jooble-country").value = button.dataset.joobleMarket;
  updateJoobleSignup();
  $("#jooble-form").scrollIntoView({ behavior: "smooth", block: "center" });
  $("#jooble-key").focus({ preventScroll: true });
});
$("#jooble-country").addEventListener("change", updateJoobleSignup);
$("#jooble-form").addEventListener("submit", (event) => {
  event.preventDefault();
  guarded(async () => {
    const button = $("#jooble-form button");
    button.disabled = true;
    try {
      await api("/api/integrations/jooble", { method: "POST", body: JSON.stringify({ country: $("#jooble-country").value, key: $("#jooble-key").value }) });
      $("#jooble-key").value = "";
      await refreshConfig();
      toast("Chave regional salva. O país está disponível nas próximas buscas da Jooble.");
    } finally { button.disabled = false; }
  });
});

guarded(async () => {
  await refreshConfig();
  $("#region").innerHTML += state.config.regions.map((region) => `<option value="${region.code}">${region.name}</option>`).join("");
  $("#region-chips").innerHTML = [{ code: "", name: "Mundo todo" }, ...["AM", "EU", "AS", "AF", "OC"].map((code) => state.config.regions.find((region) => region.code === code))]
    .map((region) => `<button type="button" class="chip${!region.code ? " active" : ""}" data-region="${region.code}" aria-pressed="${!region.code}">${!region.code ? icon("globe") : ""}${region.name}</button>`).join("");
  $("#keywords").value = state.config.defaults.keywords;
  renderCountries();
  if (state.config.preferences.keywords) await restoreFilters(state.config.preferences);
  updateGoogleLink();
  await loadFavorites();
  await navigate();
});
function updateSalaryFloor() {
  const minimum = $('#profile').value === 'custom' ? 0 : 7000;
  $('#salary-min').min = minimum;
  if (Number($('#salary-min').value) < minimum) $('#salary-min').value = minimum;
}
$('#profile').addEventListener('change', updateSalaryFloor);
$('#logout').addEventListener('click', () => guarded(async () => { await api('/api/auth/logout', {method:'POST'}); location.replace('/'); }));

async function loadProfile() {
  const result = await api('/api/profile');
  $('#profile-name').value = result.user.name;
  $('#profile-email').textContent = result.user.email + (result.user.role === 'admin' ? ' · Administração' : ' · Conta pessoal');
  $('#profile-email-to').value = result.contacts.email_to || '';
  $('#profile-chat').value = result.contacts.telegram_chat_id || '';
  const prefs = result.preferences;
  $('#preferences-summary').textContent = prefs.keywords ? `${prefs.keywords.join(' / ')} · ${prefs.country ? countryName(prefs.country) : regionName(prefs.region)} · ${money(prefs.salary_min)} por mês` : 'Você ainda não salvou um padrão. Os filtros de engenharia estão disponíveis para começar.';
}
$('#save-preferences').addEventListener('click', () => guarded(async () => {
  await api('/api/preferences', {method:'POST',body:JSON.stringify(filters())});
  await refreshConfig();
  await loadProfile();
  toast('Suas preferências foram salvas para a próxima visita.');
}));
$('#profile-form').addEventListener('submit', (event) => {
  event.preventDefault();
  guarded(async () => {
    await api('/api/profile', {method:'PATCH',body:JSON.stringify({name:$('#profile-name').value,contacts:{email_to:$('#profile-email-to').value,telegram_chat_id:$('#profile-chat').value}})});
    await refreshConfig(); toast('Perfil e destinatários atualizados.');
  });
});
$('#password-form').addEventListener('submit', (event) => {
  event.preventDefault();
  guarded(async () => {
    if ($('#new-password').value !== $('#confirm-password').value) throw new Error('As novas senhas precisam ser iguais.');
    const result = await api('/api/auth/password', {method:'POST',body:JSON.stringify({password:$('#current-password').value,new_password:$('#new-password').value})});
    csrf = result.csrf;
    $('#password-form').reset(); toast('Senha alterada. Suas outras sessões foram encerradas.');
  });
});
$('#discover-companies').addEventListener('click', () => guarded(async () => {
  const button = $('#discover-companies'); button.disabled = true;
  $('#discovery-notes').textContent = 'Pesquisando páginas de carreira e verificando anúncios compatíveis…';
  try {
    const result = await api('/api/companies/discover', {method:'POST',body:JSON.stringify(filters())});
    state.discovery = result.companies;
    $('#discovery-notes').innerHTML = result.notes.map((note) => `<p>${esc(note)}</p>`).join('');
    $('#discovery-results').innerHTML = result.companies.length ? result.companies.map((company, index) => `<article class="company-card"><h3>${esc(company.name)}</h3><span class="tag source">${esc(company.origin)}</span><div class="discovery-evidence">${company.evidence.map((job) => `<a href="${esc(job.url)}" target="_blank" rel="noopener noreferrer">${esc(job.title)} · ${esc(job.location)} ↗</a>`).join('')}</div><p>${esc(company.note)}</p><button class="button" type="button" data-discovery-add="${index}" ${company.enabled ? 'disabled' : ''}>${company.enabled ? 'Já está no seu radar' : company.registered_id ? 'Ativar no meu radar' : 'Cadastrar no meu radar'}</button></article>`).join('') : '<p>Nenhuma nova empresa com vagas verificáveis foi encontrada para esses filtros. Tente ampliar os cargos ou locais.</p>';
    $('#discovery-references').innerHTML = (result.research_sources || []).map((item) => `<p><a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)} ↗</a></p>`).join('');
    $('#discovery-grounding').innerHTML = result.search_suggestions ? `<iframe title="Sugestões da pesquisa Google" sandbox="allow-popups allow-popups-to-escape-sandbox" src="/api/search/${encodeURIComponent(result.id)}/grounding"></iframe>` : '';
  } finally { button.disabled = false; }
}));
$('#discovery-results').addEventListener('click', (event) => {
  const button = event.target.closest('[data-discovery-add]');
  if (!button) return;
  guarded(async () => {
    const company = state.discovery[Number(button.dataset.discoveryAdd)];
    button.disabled = true;
    try {
      if (company.registered_id) await api(`/api/companies/${company.registered_id}`, {method:'PATCH',body:JSON.stringify({enabled:true})});
      else await api('/api/companies', {method:'POST',body:JSON.stringify({name:company.name,url:company.url})});
      await refreshConfig(); button.textContent = 'Já está no seu radar'; toast(`${company.name} cadastrada no seu radar.`);
    } catch (error) { button.disabled = false; throw error; }
  });
});
