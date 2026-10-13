"use strict";

const onboardingState = { progress: null, step: 0, active: false, busy: false, loadVersion: 0, drafts: {} };
const tourSteps = [
  { view: 'first-steps', target: '.onboarding-welcome', title: 'Seu radar de oportunidades', text: 'Aqui você encontra seu checklist inicial. Vamos conhecer os recursos e configurar seus alertas. Você pode pausar e continuar a qualquer momento.', action: 'Ver meus primeiros passos' },
  { view: 'first-steps', target: '#onboarding-email-form', title: 'E-mail para receber vagas', text: 'Cadastre seu endereço pessoal neste formulário. A administração configura o serviço de envio. Você escolhe quais vagas enviar; salvar o endereço não dispara um e-mail.', action: 'Configurar meu e-mail', focus: '#onboarding-email' },
  { view: 'first-steps', target: '#onboarding-telegram-card', title: 'Conecte seu Telegram', text: 'Vincular Telegram abre um link pessoal do bot. Toque em Iniciar no Telegram, volte e confirme. A aplicação encontra seu chat ID. Se já tiver o número, pode cadastrá-lo manualmente.', action: 'Vincular meu Telegram', focus: '#onboarding-telegram-start' },
  { view: 'explore', target: '.filter-panel', title: 'Explorar vagas e salvar preferências', text: 'Escolha cargos, região, país, estado, salário e fontes. Produto e produção usam termos em outros idiomas e mínimo de R$ 7.000 por mês. Salários incertos ficam em Para análise. Para outras áreas, escolha Termos personalizados.', action: 'Escolher meus filtros', focus: '#keywords' },
  { view: 'explore', target: '#usage-summary', title: 'Sua cota de consultas', text: 'Veja seu saldo diário antes de buscar. O modo automático troca de fonte dentro dos seus filtros e oferece atividades quando não há novas vagas. Gemini pode organizar essas atividades se a administração permitir e houver saldo. Explorar sem Jooble mostra alternativas sem usar IA.', action: 'Ver minha cota' },
  { view: 'companies', target: '#view-companies', title: 'Empresas que você acompanha', text: 'Cadastre páginas de carreiras e ative as empresas que deseja consultar. Descobrir empresas sugere sites com anúncios verificados a partir dos seus filtros; Gemini pode ajudar quando estiver disponível.', action: 'Conhecer minhas empresas' },
  { view: 'favorites', target: '#view-favorites', title: 'Vagas salvas', text: 'Use o coração nos resultados para guardar oportunidades. As vagas salvas pertencem à sua conta e continuam disponíveis para revisar e abrir o anúncio original.', action: 'Ver minhas vagas salvas' },
  { view: 'history', target: '#view-history', title: 'Histórico de buscas', text: 'Retome os resultados de uma busca anterior sem gastar outra consulta Jooble. Confira a data e o anúncio original antes de se candidatar, porque uma vaga pode encerrar.', action: 'Conhecer meu histórico' },
  { view: 'integrations', target: '#view-integrations', title: 'Fontes e serviços conectados', text: 'Aqui você vê as fontes disponíveis. A administração cadastra as chaves de Jooble, Google Empregos e Gemini, configura o envio de e-mails e ajusta os limites compartilhados. Cada pessoa cadastra seus próprios contatos em Meu perfil.', action: 'Ver integrações' },
  { view: 'profile', target: '#view-profile', title: 'Meu perfil e próximos passos', text: 'Atualize nome, e-mail de alertas e Telegram, salve preferências e altere sua senha. Seu checklist fica em Primeiros passos. Você pode rever este tour sempre que quiser.', action: 'Abrir meu perfil', focus: '#profile-name' },
];

async function loadOnboarding() {
  const version = ++onboardingState.loadVersion;
  const result = await api('/api/onboarding');
  if (version !== onboardingState.loadVersion) return;
  onboardingState.progress = result;
  // Uma resposta antiga não substitui o contato que a pessoa está preenchendo.
  if (!onboardingState.drafts.email_to) $('#onboarding-email').value = result.contacts.email_to || '';
  if (!onboardingState.drafts.telegram_chat_id) $('#onboarding-chat').value = result.contacts.telegram_chat_id || '';
  for (const [key, label] of [['email', 'E-mail'], ['telegram', 'Telegram'], ['preferences', 'Preferências']]) {
    $(`#onboarding-${key}-badge`).textContent = `${result.checklist[key] ? '✓ Configurado' : 'Pendente'} · ${label}`;
  }
  $('#onboarding-email-status').textContent = result.email_transport_ready
    ? 'O serviço de envio está conectado. Confira seu endereço antes de salvar.'
    : 'O serviço de envio ainda precisa ser configurado pela administração. Seu endereço ficará salvo para quando o serviço estiver pronto.';
  $('#onboarding-email-admin').classList.toggle('hidden', state.config.user.role !== 'admin' || result.email_transport_ready);
  $('#onboarding-telegram-start').disabled = !result.telegram_transport_ready;
  $('#onboarding-telegram-status').textContent = !result.telegram_transport_ready
    ? 'A administração ainda precisa conectar o bot do Telegram. Você pode configurar seu e-mail e explorar vagas enquanto isso.'
    : result.checklist.telegram ? 'Chat ID salvo na sua conta. Você pode vinculá-lo novamente se trocar de Telegram.' : 'Seu bot está disponível. Vincule a sua conta para receber as vagas que selecionar.';
  $('#onboarding-preferences-status').textContent = result.checklist.preferences ? 'Suas preferências estão salvas para a próxima visita.' : 'Você ainda não salvou suas preferências.';
  const configured = Object.values(result.checklist).filter(Boolean).length;
  $('#onboarding-progress').textContent = `${configured} de 3 configurações concluídas · ${result.tour_status === 'completed' ? 'Tour concluído.' : result.tour_status === 'paused' ? 'Tour pausado; você pode continuar de onde parou.' : 'Seu tour está pronto para começar.'}`;
  $('#onboarding-resume').textContent = result.tour_status === 'completed' ? 'Rever tour' : result.tour_status === 'paused' ? 'Continuar tour' : 'Começar tour';
}

async function saveTour(status = 'paused') {
  await api('/api/onboarding', { method: 'POST', body: JSON.stringify({ tour_status: status, tour_step: onboardingState.step }) });
}

async function renderTour() {
  const step = tourSteps[onboardingState.step];
  $$('.tour-target').forEach((target) => target.classList.remove('tour-target'));
  location.hash = step.view;
  await navigate();
  const target = $(step.target);
  target?.classList.add('tour-target');
  target?.scrollIntoView({ block: 'center', behavior: 'instant' });
  $('#tour-counter').textContent = `Etapa ${onboardingState.step + 1} de ${tourSteps.length}`;
  $('#tour-title').textContent = step.title;
  $('#tour-description').textContent = step.text;
  $('#tour-action').textContent = step.action;
  $('#tour-back').disabled = onboardingState.step === 0;
  $('#tour-next').textContent = onboardingState.step === tourSteps.length - 1 ? 'Concluir tour' : 'Próximo';
  if (!$('#onboarding-tour').open) $('#onboarding-tour').showModal();
  $('#tour-next').focus();
}

async function startTour(replay = false) {
  onboardingState.step = replay || onboardingState.progress?.tour_status === 'completed' ? 0 : onboardingState.progress?.tour_step || 0;
  onboardingState.active = true;
  await saveTour();
  await renderTour();
}

async function pauseTour(completed = false) {
  await saveTour(completed ? 'completed' : 'paused');
  onboardingState.active = false;
  $('#onboarding-tour').close();
  $$('.tour-target').forEach((target) => target.classList.remove('tour-target'));
  await loadOnboarding();
  if (completed) { location.hash = 'first-steps'; await navigate(); toast('Tour concluído. Continue seu checklist em Primeiros passos.'); }
}

async function initOnboarding() {
  await loadOnboarding();
  if (onboardingState.progress.tour_status === 'new') await startTour(true);
}

async function saveSetupContacts(changes) {
  ++onboardingState.loadVersion;
  // Atualiza somente o destino escolhido; o servidor preserva os demais contatos.
  await api('/api/profile', { method: 'PATCH', body: JSON.stringify({ contacts: changes }) });
  for (const key of Object.keys(changes)) delete onboardingState.drafts[key];
  await refreshConfig();
  await loadOnboarding();
}

async function tourAction(action) {
  if (onboardingState.busy) return;
  onboardingState.busy = true;
  $('#tour-next').disabled = true;
  try { await action(); } finally { onboardingState.busy = false; $('#tour-next').disabled = false; }
}

document.addEventListener('DOMContentLoaded', () => {
  $('#onboarding-email').addEventListener('input', () => { onboardingState.drafts.email_to = true; });
  $('#onboarding-chat').addEventListener('input', () => { onboardingState.drafts.telegram_chat_id = true; });
  $('#onboarding-resume').addEventListener('click', () => guarded(() => startTour()));
  $('#onboarding-replay').addEventListener('click', () => guarded(() => startTour(true)));
  $('#tour-pause').addEventListener('click', () => guarded(() => tourAction(() => pauseTour())));
  $('#onboarding-tour').addEventListener('cancel', (event) => { event.preventDefault(); guarded(() => tourAction(() => pauseTour())); });
  $('#tour-next').addEventListener('click', () => guarded(() => tourAction(async () => {
    if (onboardingState.step === tourSteps.length - 1) return pauseTour(true);
    onboardingState.step += 1;
    await saveTour(); await renderTour();
  })));
  $('#tour-back').addEventListener('click', () => guarded(() => tourAction(async () => {
    if (!onboardingState.step) return;
    onboardingState.step -= 1; await saveTour(); await renderTour();
  })));
  $('#tour-action').addEventListener('click', () => guarded(() => tourAction(async () => {
    const step = tourSteps[onboardingState.step];
    await pauseTour();
    if (step.focus) $(step.focus)?.focus();
  })));
  $('#onboarding-email-form').addEventListener('submit', (event) => { event.preventDefault(); guarded(async () => {
    await saveSetupContacts({ email_to: $('#onboarding-email').value.trim() }); toast('Seu e-mail para alertas foi salvo.');
  }); });
  $('#onboarding-chat-form').addEventListener('submit', (event) => { event.preventDefault(); guarded(async () => {
    await saveSetupContacts({ telegram_chat_id: $('#onboarding-chat').value.trim() }); toast('Seu chat ID foi salvo.');
  }); });
  $('#onboarding-save-preferences').addEventListener('click', () => guarded(async () => {
    await api('/api/preferences', { method: 'POST', body: JSON.stringify(filters()) });
    await refreshConfig(); await loadOnboarding(); toast('Suas preferências de busca foram salvas.');
  }));
  $('#onboarding-telegram-start').addEventListener('click', () => guarded(async () => {
    const button = $('#onboarding-telegram-start'); button.disabled = true;
    try {
      const result = await api('/api/onboarding/telegram', { method: 'POST', body: '{}' });
      $('#onboarding-telegram-link').href = result.url;
      $('#onboarding-telegram-link').classList.remove('hidden');
      $('#onboarding-telegram-confirm').classList.remove('hidden');
      $('#onboarding-telegram-status').textContent = 'Abra meu bot, toque em Iniciar no Telegram e volte aqui para confirmar. O link vale por 10 minutos.';
    } finally { button.disabled = false; }
  }));
  $('#onboarding-telegram-confirm').addEventListener('click', () => guarded(async () => {
    const button = $('#onboarding-telegram-confirm'); button.disabled = true;
    try {
      const result = await api('/api/onboarding/telegram/confirm', { method: 'POST', body: '{}' });
      if (!result.ok) { $('#onboarding-telegram-status').textContent = result.message; return; }
      $('#onboarding-telegram-link').classList.add('hidden'); button.classList.add('hidden');
      await refreshConfig(); await loadOnboarding(); toast('Telegram vinculado. Seu chat ID foi salvo na sua conta.');
    } finally { button.disabled = false; }
  }));
});
