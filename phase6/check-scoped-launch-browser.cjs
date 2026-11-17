const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { randomBytes } = require('node:crypto');
const { request } = require('node:http');
const { realpathSync } = require('node:fs');
const { dirname, resolve } = require('node:path');

const origin = new URL('https://desktop-phkhegp.tail3372f6.ts.net:10000');
const mount = '/nexora-commercial';
const base = origin.origin + mount;
const api = mount + '/api/v1';
const adminAccess = api + '/admin/access';
const release = 'phase7-ar-v1';
const edge = process.env.NEXORA_EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const playwright = process.env.NEXORA_PLAYWRIGHT_CORE ||
  'C:/Users/BONDOK/Documents/GitHub/OmniRoute/node_modules/playwright-core';

function requireFixture(name, userName) {
  const allowed = ['host', 'port', 'database', 'username', 'password', 'timeout', 'command timeout', 'include error detail'];
  const fields = new Map();
  for (const field of (process.env[name] || '').split(';').filter(Boolean)) {
    const separator = field.indexOf('=');
    const key = field.slice(0, separator).trim().toLowerCase();
    assert.ok(separator > 0 && allowed.includes(key) && !fields.has(key), 'Invalid fixture connection settings');
    fields.set(key, field.slice(separator + 1).trim());
  }
  assert.equal(fields.get('host'), '127.0.0.1');
  assert.equal(fields.get('port'), '55436');
  assert.equal(fields.get('database'), 'masar_phase6_tests');
  assert.equal(fields.get('username'), userName);
}

async function backend(route, url, clientIp) {
  const incoming = route.request();
  const headers = await incoming.allHeaders();
  delete headers['proxy-authorization'];
  delete headers['proxy-connection'];
  delete headers.connection;
  delete headers['content-length'];
  const body = incoming.postDataBuffer();
  if (body) headers['content-length'] = String(body.length);
  Object.assign(headers, {
    host: origin.host, 'x-forwarded-proto': 'https', 'x-forwarded-for': clientIp, 'accept-encoding': 'identity',
  });
  return new Promise((resolveReply, reject) => {
    const outgoing = request({ hostname: '127.0.0.1', port: 5199, path: url.pathname + url.search,
      method: incoming.method(), headers, timeout: 12000 }, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('error', reject);
      response.on('end', () => {
        const headers = { ...response.headers };
        delete headers['content-length'];
        delete headers['transfer-encoding'];
        delete headers.connection;
        if ((headers['set-cookie'] || []).length > 1) { reject(new Error('Unexpected multi-cookie response in fixture')); return; }
        if (headers['set-cookie']) headers['set-cookie'] = headers['set-cookie'][0];
        resolveReply({ status: response.statusCode, headers, body: Buffer.concat(chunks) });
      });
    });
    outgoing.on('error', reject);
    outgoing.on('timeout', () => outgoing.destroy(new Error('Commercial test backend timed out')));
    outgoing.end(body ?? undefined);
  });
}

async function pageFor(browser, clientIp) {
  const context = await browser.newContext({ serviceWorkers: 'block' });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin.origin || !url.pathname.startsWith(mount + '/')) { await route.abort(); return; }
    try { await route.fulfill(await backend(route, url, clientIp)); }
    catch { await route.abort(); }
  });
  const page = await context.newPage();
  page.setDefaultTimeout(18000);
  assert.equal((await page.goto(base + '/api/v1/health'))?.status(), 200, 'QA backend health');
  return page;
}

async function http(page, method, path, status, body) {
  const result = await page.evaluate(async ({ method, path, body, api }) => {
    const headers = {};
    if (body !== undefined) {
      const csrf = await fetch(api + '/auth/csrf', { cache: 'no-store' });
      if (!csrf.ok) return { status: csrf.status, data: null };
      headers['X-CSRF-TOKEN'] = (await csrf.json()).token;
      headers['Content-Type'] = 'application/json';
    }
    const response = await fetch(path, { method, headers, cache: 'no-store', redirect: 'error',
      body: body === undefined ? undefined : JSON.stringify(body) });
    return { status: response.status, data: await response.json().catch(() => null) };
  }, { method, path, body, api });
  assert.equal(result.status, status, `${method} ${path}`);
  return result.data;
}

async function account(page, kind) {
  const userName = 'edge_launch_' + kind + '_' + randomBytes(5).toString('hex');
  await http(page, 'POST', api + '/auth/register', 201, {
    userName, displayName: 'حساب اختبار الإطلاق', password: randomBytes(24).toString('base64url'),
  });
  const cookies = await page.context().cookies(base + '/');
  assert.ok(cookies.some(c => c.name === 'Masar.CommercialTest.Session' && c.secure && c.httpOnly && c.path === mount),
    'Expected the secure QA session cookie');
  return userName;
}

async function changeAccess(panel, { type, target, action }) {
  await panel.getByLabel(/^نوع الوصول/).selectOption(type);
  await panel.getByLabel(/^الإجراء/).selectOption(action);
  await panel.getByLabel(type === 'goal' ? /^المسار/ : /^الدرس/).selectOption(target);
  await panel.getByRole('checkbox').check();
  await panel.getByRole('button', { name: action === 'grant' ? 'تأكيد تفعيل الوصول' : 'تأكيد إلغاء الوصول' }).click();
  await panel.getByText(action === 'grant' ? /^تم تفعيل / : /^تم إلغاء /).waitFor();
}

function lessonPath(id) { return `${api}/content/${release}/lessons/${id}`; }

async function visitLesson(page, id, visible) {
  await page.goto(`${base}/#lesson/${id}/${release}`);
  await page.reload();
  if (!visible) {
    await page.getByRole('heading', { name: 'هذا المحتوى غير مفعّل لحسابك' }).waitFor();
    assert.equal((await http(page, 'GET', lessonPath(id), 403)).code, 'access_required');
    return;
  }
  const lesson = await http(page, 'GET', lessonPath(id), 200);
  assert.equal(lesson.id, id);
  await page.getByRole('heading', { name: lesson.title, exact: true }).waitFor();
  assert.equal(await page.getByLabel('إصدار المحتوى', { exact: true }).count(), 0);
}

async function run() {
  requireFixture('ConnectionStrings__Masar', 'masar_app');
  requireFixture('ConnectionStrings__Migration', 'masar_bootstrap');
  const assembly = realpathSync(resolve(process.argv[2] || resolve(__dirname, '.local/launch/test-app/Masar.Api.dll')));
  const { chromium } = require(playwright);
  const browser = await chromium.launch({ executablePath: edge, headless: true });
  let stage = 'scope and fixture checks';
  try {
    const buyer = await pageFor(browser, '192.0.2.40');
    const catalog = await http(buyer, 'GET', api + '/catalog', 200);
    assert.ok(catalog.accessRequired && catalog.activeReleaseId === release, 'Expected commercial Phase 7 catalog');
    await http(buyer, 'GET', api + '/auth/csrf', 200);
    assert.ok((await buyer.context().cookies(base + '/')).some(c =>
      c.name === 'Masar.CommercialTest.Csrf' && c.secure && c.httpOnly && c.path === mount), 'Expected secure QA CSRF cookie');
    const admin = await pageFor(browser, '192.0.2.41');
    const buyerName = await account(buyer, 'learner');
    const adminName = await account(admin, 'admin');
    const promoted = spawnSync('dotnet', [assembly, '--promote-admin', adminName], {
      cwd: dirname(assembly), stdio: 'ignore', timeout: 20000,
    });
    assert.equal(promoted.status, 0, 'QA admin promotion');
    assert.equal((await http(admin, 'GET', api + '/auth/me', 200)).user.role, 'Admin');
    await http(buyer, 'GET', lessonPath('py-02'), 403);

    const prior = catalog.offers.find(offer => offer.goalId === 'python');
    let changedPrice = false;
    const grants = new Map();
    try {
      stage = 'administrator sees the release tab without a picker';
      await admin.goto(base + '/#start');
      await admin.locator('#start-title').waitFor();
      assert.equal(await admin.getByLabel('إصدار المحتوى', { exact: true }).count(), 0);
      await admin.getByRole('link', { name: 'إصدارات المحتوى', exact: true }).click();
      await admin.getByRole('heading', { name: 'إصدارات المحتوى', exact: true }).waitFor();

      stage = 'save Python price in settings';
      await admin.goto(base + '/#users');
      await admin.getByRole('heading', { name: 'إعدادات المستخدمين', exact: true }).waitFor();
      const prices = admin.getByRole('region', { name: 'أسعار المسارات', exact: true });
      await prices.getByLabel(/^المسار/).selectOption('python');
      await prices.getByLabel('السعر', { exact: true }).fill('125.25');
      await prices.getByLabel('رمز العملة', { exact: true }).fill('EGP');
      changedPrice = true;
      await prices.getByRole('button', { name: 'حفظ سعر المسار' }).click();
      await prices.getByText('تم حفظ السعر.', { exact: true }).waitFor();
      const price = new Intl.NumberFormat('ar-EG', { style: 'currency', currency: 'EGP', minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(125.25);
      await buyer.goto(base + '/#offers');
      await buyer.getByText(price, { exact: true }).waitFor();

      stage = 'find learner and grant only Python';
      const users = admin.getByRole('region', { name: 'صلاحيات المتعلمين', exact: true });
      await users.getByLabel('البحث عن متعلّم').fill(buyerName);
      await users.getByRole('button', { name: 'بحث', exact: true }).click();
      await users.getByLabel(/^حساب المتعلّم/).selectOption(buyerName);
      grants.set('python', { goalId: 'python' });
      await changeAccess(users, { type: 'goal', target: 'python', action: 'grant' });
      await visitLesson(buyer, 'py-02', true);
      await visitLesson(buyer, 'web-12', false);

      stage = 'grant one Web lesson without the Web plan';
      grants.set('web-12', { lessonId: 'web-12' });
      await changeAccess(users, { type: 'lesson', target: 'web-12', action: 'grant' });
      await visitLesson(buyer, 'web-12', true);
      await visitLesson(buyer, 'web-11', false);

      stage = 'revoke Python without resetting the learner session';
      await changeAccess(users, { type: 'goal', target: 'python', action: 'revoke' });
      grants.delete('python');
      await http(buyer, 'GET', lessonPath('py-02'), 403);
      await http(buyer, 'GET', lessonPath('web-12'), 200);
      await visitLesson(buyer, 'py-02', false);
      assert.equal((await http(buyer, 'GET', api + '/auth/me', 200)).user.userName, buyerName);
      console.log('PASSED: Edge commercial settings, public track price, plan and independent lesson grants, same-session revocation.');
    } finally {
      for (const scope of grants.values()) await http(admin, 'POST', adminAccess + '/revoke', 200, { userName: buyerName, ...scope });
      if (changedPrice) await http(admin, 'PUT', adminAccess + '/offers/python', 200,
        { price: prior?.price ?? null, currency: prior?.currency ?? null });
    }
  } catch (error) {
    const diagnostics = error.name === 'AssertionError' ? `: ${error.message.split('\n')[0]}` : '';
    console.error(`FAILED: ${stage} (${error.name}${diagnostics})`);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

run().catch(error => {
  console.error(`FAILED: browser test setup (${error.name})`);
  process.exitCode = 1;
});
