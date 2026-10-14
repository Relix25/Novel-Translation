import assert from 'node:assert/strict';
import { test } from 'node:test';
import { get, postAction } from '../src/api.js';

test('reads JSON only from the local API and rejects redirects', async (t) => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    calls.push({ path, options });
    return { ok: true, json: async () => ({ series: [] }) };
  });
  assert.deepEqual(await get('/api/state'), { series: [] });
  assert.equal(calls[0].options.redirect, 'error');
  assert.equal(calls[0].options.credentials, 'same-origin');
  assert.ok(calls[0].options.signal instanceof AbortSignal);
  await assert.rejects(get('https://example.com/api/state'), /local API/);
  assert.equal(calls.length, 1);
});

test('a mutation requires CSRF and preserves Unicode without retries', async (t) => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    calls.push({ path, options });
    return { ok: false, status: 400, json: async () => ({ error: 'Stale fingerprint' }) };
  });
  await assert.rejects(postAction({ action: 'edit' }), /Refresh Novel/);
  assert.equal(calls.length, 0);
  const action = { action: 'edit', edits: { '1:00001:example': '星の門' } };
  await assert.rejects(postAction(action, 'synthetic-csrf'), /Stale fingerprint/);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/api/action');
  assert.equal(calls[0].options.headers['X-Novel-CSRF'], 'synthetic-csrf');
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body), action);
});

test('an interrupted mutation is surfaced and is never sent again', async (t) => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => {
    throw new DOMException('Timed out', 'TimeoutError');
  });
  await assert.rejects(postAction({ action: 'review' }, 'synthetic-csrf'), /Timed out/);
  assert.equal(fetch.mock.callCount(), 1);
});

test('unexpected HTML is reported without exposing its body', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => ({
    ok: false,
    status: 502,
    json: async () => {
      throw new SyntaxError('private proxy body');
    },
  }));
  await assert.rejects(
    get('/api/state'),
    /^Error: Local server returned invalid JSON \(HTTP 502\)\.$/,
  );
});
