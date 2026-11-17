const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { randomBytes } = require('node:crypto');
const { realpathSync } = require('node:fs');
const { dirname, resolve } = require('node:path');

const origin = 'http://127.0.0.1:5196';
const api = origin + '/api/v1';
const release = 'phase7-ar-v1';
const lesson = '/content/' + release + '/lessons/data-08';
const lab = '/lab/exercises/' + release + '/data-08';
const protectedRoute = origin + '/#lesson/data-08/' + release;
const unpaidMessage = 'الوصول غير مفعّل لهذا الحساب حاليًا.';
const edge = process.env.NEXORA_EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const playwright = process.env.NEXORA_PLAYWRIGHT_CORE ||
  'C:/Users/BONDOK/Documents/GitHub/OmniRoute/node_modules/playwright-core';

function requireTestDatabase() {
  const connection = process.env.ConnectionStrings__Migration || '';
  const fields = new Map();
  for (const field of connection.split(';').filter(Boolean)) {
    const separator = field.indexOf('=');
    assert.ok(separator > 0, 'Invalid migration connection field');
    const name = field.slice(0, separator).trim().toLowerCase();
    assert.ok(!fields.has(name), 'Duplicate migration connection field');
    fields.set(name, field.slice(separator + 1).trim());
  }
  assert.ok(fields.get('database') === 'masar_phase6_tests' && fields.get('host') === '127.0.0.1',
    'The migration connection must target the loopback commercial test database');
}

async function getJson(page, path, status) {
  const response = await page.request.get(api + path, { maxRedirects: 0 });
  assert.equal(response.status(), status, path);
  return response.json();
}

async function registerBuyer(page) {
  const userName = 'phase7_browser_buyer_' + randomBytes(5).toString('hex');
  await page.goto(origin + '/#auth');
  await page.getByRole('button', { name: 'حساب جديد', exact: true }).click();
  await page.getByLabel('اسم المستخدم', { exact: true }).fill(userName);
  await page.getByLabel('الاسم الظاهر', { exact: true }).fill('حساب اختبار الواجهة');
  await page.getByLabel('كلمة المرور', { exact: true }).fill(randomBytes(24).toString('base64url'));
  const [registration] = await Promise.all([
    page.waitForResponse(response => response.url() === api + '/auth/register' && response.request().method() === 'POST'),
    page.getByRole('button', { name: 'إنشاء الحساب', exact: true }).click(),
  ]);
  assert.equal(registration.status(), 201, 'Browser registration');
  await page.waitForURL(origin + '/#plan');
  const account = (await getJson(page, '/auth/me', 200)).user;
  assert.ok(account.userName === userName && account.role === 'Learner', 'Expected the registered learner');
  return userName;
}

async function createStaff(page) {
  const userName = 'phase7_browser_staff_' + randomBytes(5).toString('hex');
  const csrf = await getJson(page, '/auth/csrf', 200);
  const response = await page.request.post(api + '/auth/register', {
    maxRedirects: 0,
    headers: { 'X-CSRF-TOKEN': csrf.token },
    data: { userName, displayName: 'حساب إدارة للاختبار', password: randomBytes(24).toString('base64url') },
  });
  assert.equal(response.status(), 201, 'Synthetic staff registration');
  return userName;
}

async function check() {
  requireTestDatabase();
  const assembly = realpathSync(resolve(process.argv[2] || resolve(__dirname, '.local/test-app/Masar.Api.dll')));
  const { chromium } = require(playwright);
  const browser = await chromium.launch({ executablePath: edge, headless: true });
  let stage = 'test instance preflight';
  try {
    const buyer = await browser.newPage();
    const admin = await browser.newPage();
    buyer.setDefaultTimeout(20000);
    admin.setDefaultTimeout(20000);
    const catalog = await getJson(buyer, '/catalog', 200);
    assert.ok(catalog.activeReleaseId === release && catalog.accessRequired === true, 'Expected Phase 7 commercial catalog');
    const health = await getJson(buyer, '/health', 200);
    assert.ok(health.status === 'ok' && health.database === 'available', 'Expected a healthy test server');
    await getJson(buyer, '/auth/csrf', 200);
    const cookies = await buyer.context().cookies(origin);
    assert.ok(cookies.some(cookie => cookie.name === 'Masar.CommercialTest.Csrf'), 'Expected commercial test session namespace');

    stage = 'guest and unpaid access';
    let privateReads = 0;
    buyer.on('request', request => {
      if (request.url().startsWith(api + '/content/')) privateReads++;
    });
    await buyer.goto(protectedRoute);
    await buyer.getByRole('heading', { name: 'منصة تعلّم مدفوعة', exact: true }).waitFor();
    await getJson(buyer, lesson, 401);
    const buyerName = await registerBuyer(buyer);
    await buyer.goto(protectedRoute);
    await buyer.getByText(unpaidMessage, { exact: true }).waitFor();
    assert.equal((await getJson(buyer, lesson, 403)).code, 'access_required');
    assert.equal((await getJson(buyer, lab, 403)).code, 'access_required');
    assert.equal(privateReads, 0, 'The browser must not fetch protected content before activation');

    stage = 'register synthetic staff';
    const adminName = await createStaff(admin);
    stage = 'promote synthetic staff';
    const promoted = spawnSync('dotnet', [assembly, '--promote-admin', adminName], {
      cwd: dirname(assembly), stdio: 'ignore', timeout: 20000,
    });
    assert.equal(promoted.status, 0, 'Could not promote the test-only staff account');
    assert.equal((await getJson(admin, '/auth/me', 200)).user.role, 'Admin');
    stage = 'render paid-access admin panel';
    await admin.goto(origin + '/#admin');
    await admin.bringToFront();
    const accessHeading = admin.getByRole('heading', { name: 'إدارة الوصول المدفوع', exact: true });
    const accessPanel = admin.locator('section').filter({ has: accessHeading });
    await accessHeading.waitFor();
    stage = 'fill activation form';
    await accessPanel.getByLabel('اسم المستخدم', { exact: true }).fill(buyerName);
    await accessPanel.getByRole('checkbox', { name: /تحققت من الشراء/ }).check();
    stage = 'submit activation form';
    const [grant] = await Promise.all([
      admin.waitForResponse(response => response.url() === api + '/admin/access/grant' && response.request().method() === 'POST'),
      accessPanel.getByRole('button', { name: 'تأكيد تفعيل الوصول', exact: true }).click(),
    ]);
    assert.equal(grant.status(), 200, 'Activation response');
    stage = 'confirm activation result';
    await accessPanel.getByText(/تم تفعيل الوصول للحساب/).waitFor();

    stage = 'Phase 7 plan and project after activation';
    await buyer.reload();
    await buyer.getByRole('heading', { name: 'مختبر البرمجة', exact: true }).waitFor();
    assert.ok(privateReads > 0, 'Expected the activated browser to load protected content');
    await buyer.goto(origin + '/#start');
    const goal = buyer.locator('a[href="#plan/data-analysis"]');
    await goal.getByRole('heading', { name: /تحليل البيانات/ }).waitFor();
    await goal.click();
    const steps = buyer.getByRole('region', { name: 'معاينة الخطة' }).locator('.plan-step a');
    await steps.first().waitFor();
    assert.equal(await steps.count(), 32);
    assert.match(await steps.nth(23).getAttribute('href'), /#lesson\/py-12\/phase7-ar-v1\//);
    assert.match(await steps.nth(24).getAttribute('href'), /#lesson\/data-01\/phase7-ar-v1\//);
    const projectStep = steps.nth(31);
    assert.match(await projectStep.getAttribute('href'), /#lesson\/data-08\/phase7-ar-v1\//);
    await projectStep.click();
    await buyer.locator('.code-lab textarea').first().waitFor();

    stage = 'choose revocation in paid-access form';
    await admin.bringToFront();
    await accessPanel.getByRole('combobox').selectOption('revoke');
    stage = 'target synthetic buyer for revocation';
    await accessPanel.getByLabel('اسم المستخدم', { exact: true }).fill(buyerName);
    stage = 'confirm revocation in paid-access form';
    await accessPanel.getByRole('checkbox', { name: /أؤكد إلغاء وصوله/ }).check();
    stage = 'submit revocation';
    const [revoke] = await Promise.all([
      admin.waitForResponse(response => response.url() === api + '/admin/access/revoke' && response.request().method() === 'POST'),
      accessPanel.getByRole('button', { name: 'تأكيد إلغاء الوصول', exact: true }).click(),
    ]);
    assert.equal(revoke.status(), 200, 'Revocation response');
    stage = 'confirm revocation result';
    await accessPanel.getByText(/تم إلغاء الوصول للحساب/).waitFor();
    stage = 'revoke content and lab in the existing session';
    assert.equal((await getJson(buyer, lesson, 403)).code, 'access_required');
    assert.equal((await getJson(buyer, lab, 403)).code, 'access_required');
    stage = 'revoke access in the browser';
    await buyer.reload();
    await buyer.getByText(unpaidMessage, { exact: true }).waitFor();
    assert.ok((await getJson(buyer, '/auth/me', 200)).user.userName === buyerName, 'Revocation keeps the session');
    console.log('PASSED: Edge denied guest and unpaid access, applied admin activation, showed the 32-step Phase 7 plan and capstone, then revoked access in the same session.');
  } catch (error) {
    const status = error.name === 'AssertionError' && typeof error.actual === 'number' &&
      typeof error.expected === 'number' ? `, expected ${error.expected}, got ${error.actual}` : '';
    console.error(`FAILED: ${stage} (${error.name}${status})`);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

check().catch(error => {
  console.error(`FAILED: commercial browser setup (${error.name})`);
  process.exitCode = 1;
});
