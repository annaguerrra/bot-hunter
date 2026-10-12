// Contratos dos lotes públicos: fila única de e-mail e confirmação por Telegram.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/app.js', 'utf8');
const helper = source.slice(source.indexOf('async function sendSelectedAlerts('), source.indexOf('$("#company-form").addEventListener'));

async function scenario(failure) {
  const calls = [];
  let telegram = 0;
  const context = vm.createContext({
    state: { config: { limits: { telegram_batch_jobs: 1 } }, searchId: 'qa-search' },
    toast: () => {}, setTimeout: (resolve) => resolve(),
    api: async (url, options) => {
      const body = JSON.parse(options.body);
      calls.push(body);
      if (body.channels[0] === 'email') return { reports: [{ channel: 'email', status: 'queued', queued: body.ids.length }] };
      telegram += 1;
      if (failure && telegram === 2) throw new Error('connection interrupted');
      return { reports: [{ channel: 'telegram', status: 'ok', sent: 1 }] };
    }
  });
  vm.runInContext(helper, context);
  const result = await context.sendSelectedAlerts(['one', 'two', 'three'], ['email', 'telegram']);
  assert.deepEqual(calls[0].ids, ['one', 'two', 'three']);
  assert.deepEqual(calls[0].channels, ['email']);
  assert.ok(calls.slice(1).every((call) => call.ids.length === 1 && call.channels[0] === 'telegram'));
  assert.equal(result.reports[0].status, 'queued');
  assert.equal(result.reports[1].sent, failure ? 1 : 3);
  assert.equal(result.reports[1].status, failure ? 'error' : 'ok');
  assert.equal(calls.length, failure ? 3 : 4);
}
Promise.resolve().then(() => scenario(false)).then(() => scenario(true)).then(() => console.log('notification batches: passed'));
