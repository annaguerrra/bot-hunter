"use strict";
const form = document.querySelector('#auth-form');
let registering = document.querySelector('.auth-card').dataset.first === 'true';
const field = (id) => document.getElementById(id);
field('auth-switch')?.addEventListener('click', () => {
  registering = !registering;
  field('register-fields').classList.toggle('hidden', !registering);
  field('confirm-fields').classList.toggle('hidden', !registering);
  field('auth-name').required = registering;
  field('auth-confirm').required = registering;
  field('auth-password').minLength = registering ? 12 : 1;
  field('auth-password').autocomplete = registering ? 'new-password' : 'current-password';
  field('auth-title').textContent = registering ? 'Crie seu radar pessoal' : 'Entre na sua conta';
  field('auth-submit').textContent = registering ? 'Criar meu radar' : 'Entrar no meu radar';
  field('auth-switch').textContent = registering ? 'Já tenho conta · Entrar' : 'Ainda não tenho conta · Criar conta';
  field('auth-error').classList.add('hidden');
});
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  field('auth-error').classList.add('hidden');
  field('auth-submit').disabled = true;
  try {
    if (registering && field('auth-password').value !== field('auth-confirm').value) throw new Error('As senhas precisam ser iguais.');
    const response = await fetch('/api/auth/' + (registering ? 'register' : 'login'), {
      method: 'POST', headers: {'Content-Type':'application/json','X-Hunter-CSRF':document.querySelector('meta[name=hunter-csrf]').content},
      body: JSON.stringify({name:field('auth-name').value,email:field('auth-email').value,password:field('auth-password').value,setup_token:field('setup-token').value})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Não foi possível entrar.');
    location.replace('/');
  } catch (error) {
    field('auth-error').textContent = error.message;
    field('auth-error').classList.remove('hidden');
  } finally { field('auth-submit').disabled = false; }
});
