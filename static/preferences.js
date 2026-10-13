"use strict";

// Sugestões locais: não usam IA, não consultam vagas e não consomem cotas.
const guidedSetup = {initialized: false, edited: false, version: 0};
function guidedTerms(profile, country) {
  const portuguese = ['BR', 'PT'].includes(country);
  const terms = {
    production: portuguese ? ['engenheiro de produção', 'engenheiro de manufatura', 'engenheiro de processos'] : ['production engineer', 'manufacturing engineer', 'industrial engineer'],
    product: portuguese ? ['engenheiro de produto', 'engenheiro de desenvolvimento de produto', 'engenheiro de projetos mecânicos'] : ['product engineer', 'product development engineer', 'mechanical design engineer'],
    both: portuguese ? ['engenheiro de produto', 'engenheiro de produção', 'engenheiro de manufatura'] : ['product engineer', 'production engineer', 'manufacturing engineer'],
  };
  return terms[profile] || [];
}
function guidedProfile() { return $('input[name="guided-area"]:checked').value; }
function updateGuidedSuggestion(force = false) {
  const profile = guidedProfile();
  const floor = profile === 'custom' ? 0 : 7000;
  $('#guided-min').min = floor;
  if (force && Number($('#guided-min').value) < floor) $('#guided-min').value = floor;
  $('#guided-max').min = $('#guided-min').value;
  $('#guided-max').setCustomValidity($('#guided-max').value && Number($('#guided-max').value) < Number($('#guided-min').value) ? 'O máximo precisa ser igual ou maior que o mínimo.' : '');
  if (!guidedSetup.edited || force) $('#guided-keywords').value = guidedTerms(profile, $('#guided-country').value).join(';');
  $('#guided-suggestion').textContent = profile === 'custom' ? 'Digite até três cargos específicos. Ex.: analista financeiro;contador. A busca exige seus termos no título.' : 'Termos sugeridos para esta área. Você pode editar até três cargos; o radar amplia os termos com sinônimos e idiomas locais.';
  $('#guided-regenerate').classList.toggle('hidden', profile === 'custom');
}
function guidedCountries(selected = '') {
  const region = $('#guided-region').value;
  $('#guided-country').innerHTML = '<option value="">Todos os países</option>' + state.config.countries.filter((item) => !region || item.region === region).map((item) => `<option value="${esc(item.code)}">${esc(item.name)}</option>`).join('');
  $('#guided-country').value = selected;
}
async function guidedStates(selected = '') {
  const version = ++guidedSetup.version, country = $('#guided-country').value;
  const select = $('#guided-state');
  select.disabled = true;
  select.innerHTML = `<option value="">${country ? 'Carregando estados…' : 'Escolha um país primeiro'}</option>`;
  if (!country) return;
  try {
    const result = await api(`/api/states/${encodeURIComponent(country)}`);
    if (version !== guidedSetup.version) return;
    select.innerHTML = '<option value="">Todos os estados / províncias</option>' + result.states.map((item) => `<option value="${esc(item.code)}">${esc(item.name)}</option>`).join('');
    select.disabled = !result.states.length;
    select.value = selected;
  } catch (error) {
    if (version !== guidedSetup.version) return;
    select.innerHTML = '<option value="">Estados indisponíveis · tente selecionar o país novamente</option>';
    toast(error.message, true);
  }
}
function initGuidedSetup() {
  if (guidedSetup.initialized) return;
  guidedSetup.initialized = true;
  const prefs = state.config.preferences;
  $('#guided-region').innerHTML = '<option value="">Mundo todo</option>' + state.config.regions.map((item) => `<option value="${esc(item.code)}">${esc(item.name)}</option>`).join('');
  $('#guided-region').value = prefs.region || '';
  guidedCountries(prefs.country || '');
  $(`input[name="guided-area"][value="${prefs.profile || 'both'}"]`).checked = true;
  $('#guided-city').value = prefs.city || '';
  $('#guided-remote').checked = Boolean(prefs.remote);
  $('#guided-min').value = prefs.salary_min ?? 7000;
  $('#guided-max').value = prefs.salary_max ?? '';
  updateGuidedSuggestion();
  if (prefs.keywords) { $('#guided-keywords').value = prefs.keywords.join(';'); guidedSetup.edited = true; }
  void guidedStates(prefs.state || '');
}
$$('input[name="guided-area"]').forEach((input) => input.addEventListener('change', () => {
  guidedSetup.edited = false; updateGuidedSuggestion(true);
}));
$('#guided-region').addEventListener('change', () => { guidedCountries(); void guidedStates(); updateGuidedSuggestion(); });
$('#guided-country').addEventListener('change', () => { void guidedStates(); updateGuidedSuggestion(); });
$('#guided-keywords').addEventListener('input', () => { guidedSetup.edited = true; });
$('#guided-regenerate').addEventListener('click', () => { guidedSetup.edited = false; updateGuidedSuggestion(true); });
['guided-min', 'guided-max'].forEach((id) => $('#' + id).addEventListener('input', () => updateGuidedSuggestion()));
$('#guided-setup').addEventListener('submit', (event) => {
  event.preventDefault(); guarded(async () => {
    const button = $('#guided-setup button[type="submit"]'), label = button.textContent;
    button.disabled = true; button.textContent = 'Salvando suas preferências…';
    try {
      const selected = {...filters(), profile: guidedProfile(), keywords: $('#guided-keywords').value, region: $('#guided-region').value,
        country: $('#guided-country').value, state: $('#guided-state').value, city: $('#guided-city').value,
        remote: $('#guided-remote').checked, salary_min: Number($('#guided-min').value),
        salary_max: $('#guided-max').value.trim() ? Number($('#guided-max').value) : null, multilingual: true, strict_title: true};
      await api('/api/preferences', {method: 'POST', body: JSON.stringify(selected)});
      // O servidor validou; só então substituímos os filtros da busca atual.
      await refreshConfig();
      await restoreFilters(state.config.preferences);
      await loadOnboarding();
      $('#guided-status').textContent = 'Seu radar está pronto. Confira os filtros e clique em Encontrar oportunidades quando quiser buscar.';
      location.hash = 'explore';
      toast('Preferências salvas. Seu radar está pronto para buscar.');
    } finally { button.disabled = false; button.textContent = label; }
  });
});
// Se a configuração chegou antes deste script, inicializamos sem esperar outra requisição.
if (state.config) initGuidedSetup();
