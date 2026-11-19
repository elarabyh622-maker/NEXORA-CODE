import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';

const source = await readFile(new URL('../src/api.ts', import.meta.url), 'utf8');
const compiled = stripTypeScriptTypes(source, { mode: 'transform' });
const { request, verifySession, SESSION_INVALIDATED } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const scope = (userId = 'account-a', signal = new AbortController().signal) => ({ userId, signal });
const account = (id) => ({ user: { id, userName: id, displayName: id, role: 'Learner' } });

test('public app mounts send catalogue requests and downloads to their own path', async t => {
  const originalWindow = globalThis.window;
  t.after(() => { globalThis.window = originalWindow; });
  const urls = [];
  t.mock.method(globalThis, 'fetch', async url => { urls.push(url); return json({}); });
  const cases = [
    ['/nexora-commercial/', '/nexora-commercial'],
    ['/nexora-pilot/', '/nexora-pilot'],
    ['/nexora-commercial-preview/', ''],
  ];
  for (const [pathname, prefix] of cases) {
    globalThis.window = { location: { pathname } };
    const mounted = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}#${pathname}`);
    await mounted.request('/catalog');
    assert.equal(urls.at(-1), `${prefix}/api/v1/catalog`);
    assert.equal(mounted.applicationPath('/projects/web-starter-v1.zip'), `${prefix}/projects/web-starter-v1.zip`);
  }
});

function responses(t, ...values) {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options });
    const value = values.shift();
    assert.ok(value, `Unexpected fetch to ${url}`);
    return typeof value === 'function' ? value() : value;
  });
  const originalWindow = globalThis.window;
  const events = new EventTarget();
  globalThis.window = events;
  t.after(() => { globalThis.window = originalWindow; });
  return { calls, events };
}

test('login and logout use the current account-bound CSRF token and same-origin cookies', async t => {
  const { calls } = responses(t, json({ token: 'guest-csrf', userId: null }), json(account('account-a')),
    json({ token: 'account-csrf', userId: 'account-a' }), new Response(null, { status: 204 }));
  await request('/auth/login', { method: 'POST', scope: scope(null), body: { userName: 'learner', password: 'test-only-value' } });
  await request('/auth/logout', { method: 'POST', scope: scope() });
  assert.equal(calls[1].options.headers['X-CSRF-TOKEN'], 'guest-csrf');
  assert.equal(calls[3].options.headers['X-CSRF-TOKEN'], 'account-csrf');
  assert.ok(calls.every(call => call.options.credentials === 'same-origin'));
  assert.equal(calls.length, 4);
});

test('verification requires /auth/me and /auth/csrf to identify the same account', async t => {
  const { calls } = responses(t, json(account('account-a')), json({ token: 'first-token', userId: 'account-b' }),
    json(account('account-b')), json({ token: 'second-token', userId: 'account-b' }));
  await assert.rejects(verifySession(scope().signal), error => error.code === 'session_changed');
  assert.equal((await verifySession(scope().signal)).id, 'account-b');
  assert.deepEqual(calls.map(call => call.url), ['/api/v1/auth/me', '/api/v1/auth/csrf', '/api/v1/auth/me', '/api/v1/auth/csrf']);
});

test('guest verification accepts 401 from /auth/me only with a guest CSRF token', async t => {
  responses(t, json({ code: 'unauthorized' }, 401), json({ token: 'guest-token', userId: null }));
  assert.equal(await verifySession(scope(null).signal), null);
});

test('a CSRF token for a different account stops a draft write before sending its text', async t => {
  const { calls, events } = responses(t, json({ token: 'account-b-csrf', userId: 'account-b' }));
  let invalidated = false;
  events.addEventListener(SESSION_INVALIDATED, () => { invalidated = true; });
  await assert.rejects(request('/me/drafts/release/exercise', {
    method: 'PUT', scope: scope(), body: { answer: 'إجابة الحساب الأول', expectedVersion: 0 },
  }), error => error.code === 'session_changed');
  assert.deepEqual(calls.map(call => call.url), ['/api/v1/auth/csrf']);
  assert.equal(calls[0].options.body, undefined);
  assert.equal(invalidated, true);
});

test('a token without an explicit userId stops a mutation', async t => {
  const { calls } = responses(t, json({ token: 'missing-owner' }));
  await assert.rejects(request('/learning-plans', { method: 'POST', scope: scope(), body: {} }), error => error.code === 'csrf_unavailable');
  assert.equal(calls.length, 1);
});

test('protected reads and writes require a verified scope', async t => {
  const { calls } = responses(t);
  await assert.rejects(request('/me/plan'), error => error.code === 'session_unverified');
  await assert.rejects(request('/plan-previews', { method: 'POST' }), error => error.code === 'session_unverified');
  assert.equal(calls.length, 0);
});

test('a session change during a private read prevents delivery of another account’s draft', async t => {
  const { calls } = responses(t, json({ answer: 'نسخة الحساب الثاني', version: 3 }), json(account('account-b')));
  await assert.rejects(request('/me/drafts/release/exercise', { scope: scope() }), error => error.code === 'session_changed');
  assert.deepEqual(calls.map(call => call.url), ['/api/v1/me/drafts/release/exercise', '/api/v1/auth/me']);
});

test('a missing draft is interpreted only for the verified owner', async t => {
  responses(t, json({ code: 'not_found' }, 404), json(account('account-b')),
    json({ code: 'not_found' }, 404), json(account('account-a')));
  await assert.rejects(request('/me/drafts/release/exercise', { scope: scope() }), error => error.code === 'session_changed');
  await assert.rejects(request('/me/drafts/release/exercise', { scope: scope() }), error => error.status === 404);
});

test('a response received after its session was replaced is discarded', async t => {
  const controller = new AbortController();
  let complete;
  const response = new Promise(resolve => { complete = resolve; });
  const { calls } = responses(t, () => response);
  const reading = request('/me/plan', { scope: scope('account-a', controller.signal) });
  controller.abort();
  complete(json({ id: 'old-plan' }));
  await assert.rejects(reading, error => error.name === 'AbortError');
  assert.equal(calls.length, 1);
});

test('session invalidation while fetching CSRF prevents dispatch of the old mutation', async t => {
  const controller = new AbortController();
  let complete;
  const response = new Promise(resolve => { complete = resolve; });
  const { calls } = responses(t, () => response);
  const writing = request('/me/drafts/release/exercise', { method: 'PUT', scope: scope('account-a', controller.signal), body: { answer: 'قديم' } });
  controller.abort();
  complete(json({ token: 'old-token', userId: 'account-a' }));
  await assert.rejects(writing, error => error.name === 'AbortError');
  assert.equal(calls.length, 1);
});

test('HTML served in place of the API is an error, never a fake success', async t => {
  responses(t, new Response('<html>SPA fallback</html>', { headers: { 'content-type': 'text/html' } }));
  await assert.rejects(request('/catalog'), error => error.status === 503 && error.code === 'unavailable');
});

test('a network failure after a mutation is not retried automatically', async t => {
  const { calls } = responses(t, json({ token: 'account-csrf', userId: 'account-a' }), () => { throw new TypeError('network unavailable'); });
  await assert.rejects(request('/practice/attempts', { method: 'POST', scope: scope(), body: { idempotencyKey: 'retained-by-caller' } }), error => error.status === 0 && /لم نؤكد/.test(error.message));
  assert.equal(calls.length, 2);
});

test('a temporarily unavailable catalogue recovers with one bounded read retry', async t => {
  const { calls } = responses(t, json({ code: 'service_unavailable' }, 503), json({ activeReleaseId: 'reviewed' }));
  assert.deepEqual(await request('/catalog'), { activeReleaseId: 'reviewed' });
  assert.equal(calls.length, 2);
});

test('catalogue retry stops after a second failure and can be cancelled', async t => {
  const { calls } = responses(t, ...Array.from({ length: 3 }, () => json({ code: 'database_unavailable' }, 503)));
  await assert.rejects(request('/catalog'), error => error.status === 503);
  assert.equal(calls.length, 2);
  const controller = new AbortController();
  const cancelled = request('/catalog', { signal: controller.signal });
  await new Promise(resolve => setTimeout(resolve, 20));
  controller.abort();
  await assert.rejects(cancelled, error => error.name === 'AbortError');
  assert.equal(calls.length, 3);
});

test('a temporary service error never replays a submitted mutation', async t => {
  const { calls } = responses(t, json({ token: 'csrf', userId: 'account-a' }), json({ code: 'service_unavailable' }, 503));
  await assert.rejects(request('/practice/attempts', { method: 'POST', scope: scope(), body: { answer: 'test' } }), error => error.status === 503);
  assert.equal(calls.length, 2);
});

test('version conflicts preserve the status for draft and release recovery', async t => {
  responses(t, json({ token: 'account-csrf', userId: 'account-a' }), json({ code: 'version_conflict', message: 'تغيرت النسخة المحفوظة.' }, 409));
  await assert.rejects(request('/me/drafts/release/exercise', { method: 'PUT', scope: scope(), body: { answer: 'نصي', expectedVersion: 1 } }), error => error.status === 409 && error.code === 'version_conflict');
});

test('401 on a private read invalidates the current scope', async t => {
  const { events } = responses(t, json({ code: 'unauthorized' }, 401));
  let invalidated = false;
  events.addEventListener(SESSION_INVALIDATED, () => { invalidated = true; });
  await assert.rejects(request('/me/progress?releaseId=sample', { scope: scope() }), error => error.status === 401 && /تسجيل الدخول/.test(error.message));
  assert.equal(invalidated, true);
});

test('403 and 503 failures have understandable Arabic recovery messages', async t => {
  responses(t, ...[403, 503].map(status => json({ code: 'failure', message: 'Internal error detail must not be shown' }, status)));
  for (const status of [403, 503]) {
    await assert.rejects(request('/catalog'), error => error.status === status && /[\u0600-\u06ff]/.test(error.message) && !error.message.includes('Internal'));
  }
});
