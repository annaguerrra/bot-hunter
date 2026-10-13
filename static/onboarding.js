"use strict";

const onboardingState = { progress: null, step: 0, active: false, busy: false, loadVersion: 0, drafts: {}, target: null, frame: 0 };
const tourSteps = [
  { view: 'first-steps', target: '#guided-setup h2', title: 'Monte seu radar em poucos passos', text: 'Escolha a área, o destino e uma faixa salarial nesta página. Sugerimos palavras-chave editáveis e salvamos os filtros. Isso não inicia buscas. E-mail e Telegram são opcionais; configure seus contatos pessoais abaixo. Você pode pausar o tour e começar agora.', action: 'Escolher minha área', focus: 'input[name="guided-area"]' },
  { view: 'first-steps', target: '#onboarding-email', title: 'E-mail para receber vagas', text: 'Cadastre seu endereço pessoal neste formulário. A administração configura o serviço de envio. Você escolhe quais vagas enviar; salvar o endereço não dispara um e-mail.', action: 'Configurar meu e-mail', focus: '#onboarding-email' },
  { view: 'first-steps', target: '#onboarding-telegram-start', title: 'Conecte seu Telegram', text: 'Vincular Telegram abre um link pessoal do bot. Toque em Iniciar no Telegram, volte e confirme. A aplicação encontra seu chat ID. Se já tiver o número, pode cadastrá-lo manualmente.', action: 'Vincular meu Telegram', focus: '#onboarding-telegram-start' },
  { view: 'explore', target: '#keywords', title: 'Explorar vagas e salvar preferências', text: 'Escolha cargos, região, país, estado, faixa salarial e fontes. Produto e produção usam termos em outros idiomas e mínimo de R$ 7.000 por mês. O máximo salarial é opcional. Salários incertos ficam em Para análise. Para outras áreas, escolha Termos personalizados.', action: 'Escolher meus filtros', focus: '#keywords' },
  { view: 'explore', target: '#usage-summary h2', title: 'Sua cota de consultas', text: 'Veja seu saldo diário antes de buscar. O modo automático troca de fonte dentro dos seus filtros e oferece atividades quando não há novas vagas. Gemini pode organizar essas atividades se a administração permitir e houver saldo. Explorar sem Jooble permite consultar apenas empresas, rever vagas e abrir a Central de Carreira, com dicas, checklist e treino de entrevistas sem IA.', action: 'Ver minha cota' },
  { view: 'companies', target: '#discover-companies', title: 'Empresas que você acompanha', text: 'Cadastre páginas de carreiras e ative as empresas que deseja consultar. O catálogo permite filtrar e adicionar empresas em lote, sem iniciar buscas. Verificar sugestões consulta cinco portais por vez. Ashby também tem integração direta; Gemini é opcional.', action: 'Conhecer minhas empresas' },
  { view: 'favorites', target: '#view-favorites h1', title: 'Vagas salvas', text: 'Use o coração nos resultados para guardar oportunidades. O coração responde imediatamente. Filtre por país, cargo, empresa, modalidade, fonte e salário sem gastar consultas. As vagas pertencem à sua conta; abra o anúncio original para conferir os detalhes.', action: 'Ver minhas vagas salvas' },
  { view: 'history', target: '#history-tabs', title: 'Buscas anteriores e todas as vagas', text: 'Por busca mostra prévias e permite abrir todos os resultados de cada pesquisa. Todas as vagas reúne seu acervo sem repetir anúncios equivalentes, com filtro de salário. Isso não gasta consultas. Confira o anúncio original antes de se candidatar.', action: 'Conhecer meu histórico' },
  { view: 'integrations', target: '#view-integrations .integration-card h2', title: 'Fontes e serviços conectados', text: 'Aqui você vê as fontes disponíveis. A administração cadastra as chaves de Jooble, Google Empregos e Gemini, configura o envio de e-mails e ajusta os limites compartilhados. Cada pessoa cadastra seus próprios contatos em Meu perfil.', action: 'Ver integrações' },
  { view: 'profile', target: '#profile-name', title: 'Meu perfil e próximos passos', text: 'Atualize nome, e-mail de alertas e Telegram, salve preferências e altere sua senha. Seu checklist fica em Primeiros passos. Você pode rever este tour sempre que quiser.', action: 'Abrir meu perfil', focus: '#profile-name' },
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
  $$('.tour-target').forEach((target) => { target.classList.remove('tour-target'); target.removeAttribute('aria-describedby'); });
  location.hash = step.view;
  await navigate();
  const target = $(step.target);
  onboardingState.target = target;
  target?.classList.add('tour-target');
  target?.setAttribute('aria-describedby', 'tour-description');
  target?.scrollIntoView({ block: 'center', behavior: 'instant' });
  $('#tour-counter').textContent = `Etapa ${onboardingState.step + 1} de ${tourSteps.length}`;
  $('#tour-title').textContent = step.title;
  $('#tour-description').textContent = step.text;
  $('#tour-action').textContent = step.action;
  $('#tour-back').disabled = onboardingState.step === 0;
  $('#tour-next').textContent = onboardingState.step === tourSteps.length - 1 ? 'Concluir tour' : 'Próximo';
  $('#onboarding-tour').classList.remove('hidden');
  positionTour(true);
  $('#tour-next').focus({preventScroll: true});
}

function positionTour(adjustAnchor = false) {
  // A dica fica ao lado do controle, sem fundo escuro, desfoque ou bloqueio da página.
  if (!onboardingState.active || !onboardingState.target) return;
  const tip = $('#onboarding-tour');
  const anchor = onboardingState.target.getBoundingClientRect();
  if (!anchor.width || !anchor.height) return;
  const viewport = window.visualViewport;
  const x = viewport?.offsetLeft || 0, y = viewport?.offsetTop || 0;
  const width = viewport?.width || innerWidth, height = viewport?.height || innerHeight;
  const space = 12, gap = 14;
  const header = getComputedStyle($('.sidebar')).position === 'sticky' ? $('.sidebar').getBoundingClientRect().bottom : y;
  const safeTop = Math.max(y, header) + space;
  tip.style.maxHeight = `${Math.max(180, y + height - safeTop - space - anchor.height - gap - 4)}px`;
  const box = tip.getBoundingClientRect();
  const placements = [
    {side: 'right', left: anchor.right + gap, top: anchor.top},
    {side: 'left', left: anchor.left - box.width - gap, top: anchor.top},
    {side: 'bottom', left: anchor.left, top: anchor.bottom + gap},
    {side: 'top', left: anchor.left, top: anchor.top - box.height - gap},
  ];
  const fits = (p) => p.left >= x + space && p.left + box.width <= x + width - space && p.top >= safeTop && p.top + box.height <= y + height - space;
  const fitting = placements.find(fits);
  if (!fitting && adjustAnchor && anchor.height + box.height + gap < y + height - safeTop - space) {
    window.scrollBy({top: anchor.top - safeTop, behavior: 'instant'});
    positionTour(false); return;
  }
  const placement = fitting || placements.slice(2).sort((a, b) => Math.abs(a.top - y) - Math.abs(b.top - y))[0];
  tip.style.left = `${Math.max(x + space, Math.min(placement.left, x + width - box.width - space))}px`;
  tip.style.top = `${Math.max(safeTop, Math.min(placement.top, y + height - box.height - space))}px`;
  tip.dataset.side = placement.side;
}

function requestTourPosition() {
  if (onboardingState.frame) return;
  onboardingState.frame = requestAnimationFrame(() => { onboardingState.frame = 0; positionTour(); });
}

async function startTour(replay = false) {
  onboardingState.step = replay || onboardingState.progress?.tour_status === 'completed' ? 0 : onboardingState.progress?.tour_step || 0;
  onboardingState.active = true;
  $('#toast').classList.add('hidden');
  document.body.classList.add('tour-active');
  await saveTour();
  await renderTour();
}

async function pauseTour(completed = false) {
  await saveTour(completed ? 'completed' : 'paused');
  onboardingState.active = false;
  document.body.classList.remove('tour-active');
  $('#onboarding-tour').classList.add('hidden');
  $$('.tour-target').forEach((target) => { target.classList.remove('tour-target'); target.removeAttribute('aria-describedby'); });
  onboardingState.target = null;
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
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && onboardingState.active && !$('dialog[open]')) { event.preventDefault(); guarded(() => tourAction(() => pauseTour())); }
  });
  window.addEventListener('resize', requestTourPosition);
  window.addEventListener('scroll', requestTourPosition, {capture: true, passive: true});
  window.visualViewport?.addEventListener('resize', requestTourPosition);
  window.visualViewport?.addEventListener('scroll', requestTourPosition);
  const observer = new ResizeObserver(requestTourPosition);
  observer.observe($('#onboarding-tour'));
  window.addEventListener('hashchange', () => {
    if (onboardingState.active && location.hash.slice(1) !== tourSteps[onboardingState.step].view) guarded(() => tourAction(() => pauseTour()));
  });
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
