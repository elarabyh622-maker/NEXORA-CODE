import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';

const extension = existsSync(new URL('../src/model.ts', import.meta.url)) ? 'ts' : 'js';
const model = await import('../src/model.' + extension);
const { createMockApi } = await import('../src/mock.' + extension);
const { createApi, ApiError } = await import('../src/api.' + extension);
const product = {id: 1, name: 'دفتر', category: 'قرطاسية', price_minor: 1250, stock: 0};
const input = {name: 'منتج اختبار', category: 'تدريب', price_minor: 125, stock: 2};

test('قراءة القيم الصحيحة والصفر ونسخ المنتجات دون تسريب المرجع', () => {
  const parsed = model.parseProduct(product);
  assert.deepEqual(parsed, product);
  assert.notEqual(parsed, product);
  const list = model.parseProducts([product]);
  assert.notEqual(list[0], product);
  assert.equal(model.parseProducts([]).length, 0);
  assert.ok(model.formatPrice(1250).includes('١٢'));
});

test('رفض المدخلات الخارجية والكسور والقيم خارج الحدود', () => {
  for (const value of [null, [], {...input, name: ''}, {...input, name: '\0bad'},
    {...input, category: ''}, {...input, stock: '2'}, {...input, stock: -1},
    {...input, stock: 0.5}, {...input, price_minor: 1.5}, {...input, price_minor: NaN},
    {...input, price_minor: 100000001}]) {
    assert.throws(() => model.parseInput(value));
  }
});

test('رفض قائمة أو هوية مخالفة للعقد وتكرار المعرفات', () => {
  for (const value of [null, {}, [product, product], [{...product, id: '1'}], [{...product, id: 0}],
    [{...product, name: null}]]) assert.throws(() => model.parseProducts(value));
  assert.deepEqual(model.parseUser({username: 'reader', role: 'reader'}), {username: 'reader', role: 'reader'});
  for (const role of ['', 'owner', null]) assert.throws(() => model.parseUser({username: 'x', role}));
});

test('تمييز الحقل الرقمي الفارغ عن الصفر قبل الحفظ', () => {
  assert.equal(model.readIntegerField('0'), 0);
  assert.equal(model.readIntegerField('125'), 125);
  for (const value of ['', ' ', null, '1.5', 'x', 'Infinity']) assert.throws(() => model.readIntegerField(value));
});

test('تصفية المصدر المحاكي وإرجاع نسخ مستقلة', async () => {
  const api = createMockApi();
  const all = await api.list({q: '', category: ''});
  assert.equal(all.length, 2);
  all[0].name = 'تغيير خارج المخزن';
  const selected = await api.list({q: 'دفتر', category: 'قرطاسية'});
  assert.equal(selected.length, 1);
  assert.equal(selected[0].id, 1);
  assert.deepEqual(await api.list({q: 'لا يوجد', category: ''}), []);
  const abort = new AbortController();
  abort.abort();
  await assert.rejects(api.list({q: '', category: ''}, abort.signal));
});

test('الحفظ المحاكي يستبدل المنتج ويترك النسخة القديمة مستقلة', async () => {
  const api = createMockApi();
  const token = await api.login('admin', 'training');
  const before = await api.list({q: '', category: ''});
  const updated = await api.save(token, {...input, stock: 0}, before[0].id);
  const after = await api.list({q: '', category: ''});
  assert.equal(updated.stock, 0);
  assert.equal(after[0].name, input.name);
  assert.equal(before[0].name, 'دفتر رسم');
  const added = await api.save(token, input);
  assert.notEqual(added.id, before[0].id);
  await api.remove(token, added.id);
  await assert.rejects(api.save(token, input, added.id), error => error.status === 404);
});

test('الجلسة والدور مطلوبان في مصدر التدريب وتسجيل الخروج يبطلها', async () => {
  const api = createMockApi();
  await assert.rejects(api.login('admin', 'wrong'), error => error.status === 401);
  await assert.rejects(api.save('', input), error => error.status === 401);
  const reader = await api.login('reader', 'training');
  assert.equal((await api.me(reader)).role, 'reader');
  await assert.rejects(api.save(reader, input), error => error.status === 403);
  await assert.rejects(api.remove(reader, 1), error => error.status === 403);
  await api.logout(reader);
  await assert.rejects(api.me(reader), error => error.status === 401);
});

test('محوّل API يقرأ JSON ويشفّر البحث ويمرر الإلغاء', async () => {
  const controller = new AbortController();
  let seen;
  const api = createApi(async (url, options) => {
    seen = {url, options};
    return new Response(JSON.stringify([product]), {status: 200, headers: {'Content-Type': 'application/json'}});
  });
  assert.deepEqual(await api.list({q: "O'Brien & قلم", category: 'قرطاسية'}, controller.signal), [product]);
  const query = new URL(seen.url, 'http://127.0.0.1').searchParams;
  assert.equal(query.get('q'), "O'Brien & قلم");
  assert.equal(query.get('category'), 'قرطاسية');
  assert.equal(seen.options.signal, controller.signal);
});

test('محوّل API يرفض خطأ HTTP وJSON المخالف بدل اعتباره نجاحًا', async () => {
  const failed = createApi(async () => new Response(JSON.stringify({detail: 'رفض'}), {status: 403}));
  await assert.rejects(failed.list({q: '', category: ''}), error => error instanceof ApiError && error.status === 403);
  for (const body of ['invalid', JSON.stringify({items: []}), JSON.stringify([{...product, stock: '2'}])]) {
    const api = createApi(async () => new Response(body, {status: 200}));
    await assert.rejects(api.list({q: '', category: ''}));
  }
});

test('محوّل API يرسل الجلسة في الترويسة ويتعامل مع 204 دون JSON', async () => {
  const calls = [];
  const api = createApi(async (url, options) => {
    calls.push({url, options});
    if (url === '/api/login') return new Response(JSON.stringify({access_token: 'test-token', token_type: 'bearer', role: 'admin'}));
    if (url === '/api/me') return new Response(JSON.stringify({username: 'test-user', role: 'admin'}));
    if (options.method === 'DELETE' || url === '/api/logout') return new Response(null, {status: 204});
    return new Response(JSON.stringify(product), {status: options.method === 'POST' ? 201 : 200});
  });
  const token = await api.login('test-user', 'test-password');
  assert.equal((await api.me(token)).role, 'admin');
  await api.save(token, input);
  await api.save(token, input, 1);
  await api.remove(token, 1);
  await api.logout(token);
  assert.deepEqual(calls.map(call => call.options.method), ['POST', 'GET', 'POST', 'PUT', 'DELETE', 'POST']);
  for (const call of calls.slice(1)) assert.equal(call.options.headers.get('Authorization'), 'Bearer test-token');
  assert.equal(calls[2].options.headers.get('Content-Type'), 'application/json');
  assert.deepEqual(JSON.parse(calls[2].options.body), input);
});
