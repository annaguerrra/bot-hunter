"use strict";

// Catálogo público e progresso pessoal são carregados sem chamar APIs de vagas.
const companyCatalog = {offset: 0, total: 0, companies: [], selected: new Set(), version: 0};
const careerView = {version: 0, toolsLoaded: false};

function renderCompanySelection() {
  $('#company-search-limit').textContent = state.config.limits.company_search_limit;
  const enabled = state.config.companies.filter((company) => company.enabled);
  $('#company-selection').innerHTML = enabled.length ? enabled.map((company) => `<label class="checkbox-label"><input type="checkbox" data-search-company="${company.id}" ${!state.companySelection || state.companySelection.has(company.id) ? 'checked' : ''}><span>${esc(company.name)}</span></label>`).join('') : '<p class="field-help">Adicione ou ative uma empresa em Empresas.</p>';
  if (!$('#company-catalog-country').dataset.ready) {
    $('#company-catalog-country').innerHTML += state.config.countries.map((item) => `<option value="${esc(item.code)}">${esc(item.name)}</option>`).join('');
    $('#company-catalog-region').innerHTML += state.config.regions.map((item) => `<option value="${esc(item.code)}">${esc(item.name)}</option>`).join('');
    $('#company-catalog-country').dataset.ready = 'true';
  }
}

$('#company-selection').addEventListener('change', () => {
  state.companySelection = new Set($$('#company-selection input:checked').map((input) => Number(input.dataset.searchCompany)));
});
$('#radar-prev').addEventListener('click', () => { state.radarOffset -= 20; renderCompanies(); });
$('#radar-next').addEventListener('click', () => { state.radarOffset += 20; renderCompanies(); });

function catalogSelectionStatus() {
  const count = companyCatalog.selected.size;
  $('#company-catalog-add').textContent = `Adicionar selecionadas (${count})`;
  $('#company-catalog-add').disabled = !count || count > 20;
}

async function loadCompanyCatalog(offset = 0) {
  const version = ++companyCatalog.version;
  const params = new URLSearchParams({offset, q: $('#company-catalog-query').value,
    provider: $('#company-catalog-provider').value, area: $('#company-catalog-area').value,
    country: $('#company-catalog-country').value, region: $('#company-catalog-region').value,
    geography: $('#company-catalog-geography').value, profile: $('#profile').value});
  const result = await api(`/api/companies/catalog?${params}`);
  if (version !== companyCatalog.version) return;
  Object.assign(companyCatalog, {offset: result.offset, total: result.total, companies: result.companies});
  if (!$('#company-catalog-area').dataset.ready) {
    $('#company-catalog-area').innerHTML += result.areas.map((item) => `<option value="${esc(item)}">${esc(item)}</option>`).join('');
    $('#company-catalog-area').dataset.ready = 'true';
  }
  $('#company-catalog-count').textContent = `${result.total} empresas nestes filtros · até 20 por lote`;
  $('#company-catalog-list').innerHTML = result.companies.length ? result.companies.map((company) => {
    const registered = company.registered_id != null;
    const available = company.status === 'validated' && !registered;
    const status = registered ? (company.enabled ? 'No seu radar' : 'Pausada no seu radar') : company.status === 'validated' ? 'API validada · disponível' : company.status === 'manual_only' ? 'Somente link externo' : 'Validação pendente';
    const geography = company.geography.map((code) => code === 'global' ? 'Internacional' : countryName(code)).join(' / ');
    return `<article class="development-card"><div class="development-card-heading"><h3>${esc(company.name)}</h3>${available ? `<label class="catalog-check"><input type="checkbox" data-catalog-select="${esc(company.catalog_id)}" aria-label="Selecionar ${esc(company.name)}" ${companyCatalog.selected.has(company.catalog_id) ? 'checked' : ''}></label>` : ''}</div><span class="tag source">${esc(company.provider === 'ashby' ? 'Ashby' : providerName(company.provider))}</span><p class="company-areas">${esc(company.tags.slice(0, 4).join(' · '))}</p><p class="field-help">Abrangência: ${esc(geography)}</p><p class="catalog-status">${esc(status)}</p><p class="field-help">Vagas compatíveis: não verificadas${company.validated_at ? ` · API conferida em ${esc(new Date(company.validated_at + 'T12:00:00').toLocaleDateString('pt-BR'))}` : ''}</p>${company.reason ? `<p class="field-help">${esc(company.reason)}</p>` : ''}<div class="development-card-actions"><a class="button" href="${esc(company.url)}" target="_blank" rel="noopener noreferrer">Ver carreiras ↗</a><button class="button primary" data-catalog-add="${esc(company.catalog_id)}" ${available ? '' : 'disabled'}>${registered ? 'Já cadastrada' : company.status === 'validated' ? 'Adicionar ao radar' : 'Integração pendente'}</button></div></article>`;
  }).join('') : empty('Nenhuma empresa nestes filtros.', 'Amplie a área ou localização para explorar outros portais.', 'building');
  $('#company-catalog-prev').disabled = !result.offset;
  $('#company-catalog-next').disabled = result.offset + result.limit >= result.total;
  $('#company-catalog-page').textContent = `Página ${Math.floor(result.offset / result.limit) + 1} de ${Math.max(1, Math.ceil(result.total / result.limit))}`;
  catalogSelectionStatus();
}

async function addCatalogCompanies(ids, button) {
  button.disabled = true;
  try {
    const result = await api('/api/companies/catalog', {method: 'POST', body: JSON.stringify({ids})});
    ids.forEach((id) => companyCatalog.selected.delete(id));
    await refreshConfig();
    await loadCompanyCatalog(companyCatalog.offset);
    toast(`${result.added} empresas adicionadas; ${result.existing} já cadastradas. Nenhuma busca foi iniciada.`);
  } finally { if (button.id !== 'company-catalog-add') button.disabled = false; catalogSelectionStatus(); }
}

$('#company-catalog-list').addEventListener('change', (event) => {
  const input = event.target.closest('[data-catalog-select]');
  if (!input) return;
  if (input.checked && companyCatalog.selected.size >= 20) { input.checked = false; toast('Selecione até 20 empresas por lote.', true); return; }
  if (input.checked) companyCatalog.selected.add(input.dataset.catalogSelect);
  else companyCatalog.selected.delete(input.dataset.catalogSelect);
  catalogSelectionStatus();
});
$('#company-catalog-list').addEventListener('click', (event) => {
  const button = event.target.closest('[data-catalog-add]');
  if (button) guarded(() => addCatalogCompanies([button.dataset.catalogAdd], button));
});
$('#company-catalog-add').addEventListener('click', (event) => guarded(() => addCatalogCompanies([...companyCatalog.selected], event.currentTarget)));
$('#company-catalog-prev').addEventListener('click', () => guarded(() => loadCompanyCatalog(companyCatalog.offset - 10)));
$('#company-catalog-next').addEventListener('click', () => guarded(() => loadCompanyCatalog(companyCatalog.offset + 10)));
['provider', 'area', 'country', 'region', 'geography'].forEach((key) => $(`#company-catalog-${key}`).addEventListener('change', () => {
  companyCatalog.selected.clear(); guarded(() => loadCompanyCatalog());
}));
let companyQueryTimer;
$('#company-catalog-query').addEventListener('input', () => {
  companyCatalog.selected.clear(); catalogSelectionStatus();
  clearTimeout(companyQueryTimer); companyQueryTimer = setTimeout(() => guarded(() => loadCompanyCatalog()), 250);
});

$('#free-company-search').addEventListener('click', () => {
  $('#free-exploration').checked = true;
  $('#auto-sources').checked = false;
  $('#discovery-use-gemini').checked = false;
  if (!filters().company_ids.length) { location.hash = 'companies'; toast('Adicione ou ative uma empresa para consultar seus anúncios.'); return; }
  location.hash = 'explore'; startSearch();
});
$('#free-exploration').addEventListener('change', () => {
  if ($('#free-exploration').checked) { $('#auto-sources').checked = false; $('#discovery-use-gemini').checked = false; }
});

async function loadCareer() {
  const version = ++careerView.version;
  const params = new URLSearchParams({category: $('#career-category').value, q: $('#career-query').value, profile: $('#profile').value});
  const result = await api(`/api/career?${params}`);
  if (version !== careerView.version) return;
  $('#career-count').textContent = `${result.resources.length} orientações · conteúdos em português; fontes originais em inglês`;
  $('#career-resources').innerHTML = result.resources.length ? result.resources.map((item) => `<article class="development-card career-card"><span class="section-kicker">${esc(item.category_name)}</span><h2>${esc(item.title)}</h2><p>${esc(item.summary)}</p><div class="career-action"><strong>Experimente agora</strong><p>${esc(item.action)}</p></div><div class="career-source"><span>Fonte: ${esc(item.source_name)}</span><a href="${esc(item.source_url)}" target="_blank" rel="noopener noreferrer">Ver conteúdo original ↗</a><small>Referência conferida em ${esc(new Date(item.verified_at + 'T12:00:00').toLocaleDateString('pt-BR'))}</small></div></article>`).join('') : empty('Nenhum conteúdo nestes filtros.', 'Tente outro tema ou palavra-chave.', 'briefcase');
  if (!careerView.toolsLoaded) {
    const progress = result.progress;
    $('#career-checklist').innerHTML = result.checklist.map((item) => `<label class="checkbox-label"><input type="checkbox" value="${esc(item.id)}" ${(progress.checklist || []).includes(item.id) ? 'checked' : ''}><span>${esc(item.label)}</span></label>`).join('');
    $('#star-question').innerHTML = result.questions.map((item) => `<option value="${esc(item.id)}">${esc(item.text)}</option>`).join('');
    const star = progress.star || {};
    $('#star-question').value = star.question || 'process';
    ['situation', 'task', 'action', 'result'].forEach((key) => { $(`#star-${key}`).value = star[key] || ''; });
    careerView.toolsLoaded = true;
  }
  updateCareerChecklist();
}

function updateCareerChecklist() {
  $('#career-checklist-count').textContent = `${$$('#career-checklist input:checked').length} de ${$$('#career-checklist input').length} etapas concluídas`;
}
$('#career-checklist').addEventListener('change', updateCareerChecklist);
$('#career-progress-form').addEventListener('input', () => { $('#career-save-status').textContent = 'Há alterações para salvar. Seu rascunho é pessoal.'; });
$('#career-progress-form').addEventListener('submit', (event) => {
  event.preventDefault(); guarded(async () => {
    const button = $('#career-progress-form button[type="submit"]'); button.disabled = true;
    try {
      const star = {question: $('#star-question').value};
      ['situation', 'task', 'action', 'result'].forEach((key) => { star[key] = $(`#star-${key}`).value; });
      await api('/api/career/progress', {method: 'PUT', body: JSON.stringify({checklist: $$('#career-checklist input:checked').map((input) => input.value), star})});
      $('#career-save-status').textContent = 'Progresso e rascunho salvos na sua conta.';
      toast('Seu progresso foi salvo.');
    } finally { button.disabled = false; }
  });
});
$('#career-category').addEventListener('change', () => guarded(loadCareer));
let careerQueryTimer;
$('#career-query').addEventListener('input', () => { clearTimeout(careerQueryTimer); careerQueryTimer = setTimeout(() => guarded(loadCareer), 250); });
