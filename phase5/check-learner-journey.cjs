const assert = require('node:assert/strict');
const { readFile } = require('node:fs/promises');

const release = 'phase4-ar-v1';
const goals = ['explore', 'python', 'web'];
const edge = process.env.NEXORA_EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const playwright = process.env.NEXORA_PLAYWRIGHT_CORE ||
  'C:/Users/BONDOK/Documents/GitHub/OmniRoute/node_modules/playwright-core';

function lessonIds(prefix) {
  return Array.from({ length: 12 }, (_, index) => `${prefix}-${String(index + 1).padStart(2, '0')}`);
}

function goalLink(page, goal) {
  return page.locator(`section[aria-labelledby="start-goals"] a[href="#plan/${goal}"]`);
}

function planLesson(page, lesson) {
  return page.locator(`.plan-list a[href^="#lesson/${lesson}/${release}"]`);
}

async function visitStart(page, origin) {
  if (page.url() === 'about:blank') {
    const response = await page.goto(origin);
    assert.equal(response?.status(), 200);
  } else {
    await page.getByRole('navigation').locator('a[href="#start"]').click();
  }
  await page.locator('#start-goals').waitFor();
}

async function openPlan(page, origin, goal) {
  await visitStart(page, origin);
  await goalLink(page, goal).click();
  await page.locator('.plan-list li').first().waitFor();
  assert.equal(await page.getByLabel('ما الذي تريد استكشافه؟').inputValue(), goal);
}

async function checkPlan(page, expectedIds) {
  const links = await page.locator('.plan-list .plan-step a').evaluateAll(items =>
    items.map(item => item.getAttribute('href').split('/')));
  assert.deepEqual(links.map(([, id]) => id), expectedIds);
  assert.ok(links.every(([route, , linkedRelease]) => route === '#lesson' && linkedRelease === release));
  const reasons = await page.locator('.plan-list .plan-step .reason').allTextContents();
  assert.equal(reasons.length, expectedIds.length);
  assert.ok(reasons.every(reason => /\p{Script=Arabic}/u.test(reason)), 'Each step should show a reason in Arabic');
}

async function checkExample(page, expectedCode) {
  const example = page.locator('.example pre code').first();
  await example.waitFor();
  assert.match(await example.textContent(), expectedCode);
}

const checks = [
  ['Active release and three beginner goals', async (page, origin) => {
    await visitStart(page, origin);
    assert.equal(await page.getByLabel('إصدار المحتوى').inputValue(), release);
    const cards = page.locator('section[aria-labelledby="start-goals"] .goals a');
    const hrefs = await cards.evaluateAll(links => links.map(link => link.getAttribute('href')));
    assert.deepEqual(hrefs, goals.map(goal => `#plan/${goal}`));
    const tracks = page.locator('details.curriculum-track');
    assert.equal(await tracks.count(), 3);
    assert.equal(await tracks.locator('a.lesson-card').count(), 36);
    assert.equal(await page.locator('section[aria-labelledby="curriculum-projects"] a').count(), 3);
    await page.getByRole('link', { name: 'دخول / حساب جديد' }).waitFor();
    await goalLink(page, 'explore').click();
    await page.locator('.plan-list li').first().waitFor();
    await checkPlan(page, lessonIds('core'));
  }],
  ['Python plan, common prerequisites, Python example and guest hint', async (page, origin) => {
    await openPlan(page, origin, 'python');
    await checkPlan(page, [...lessonIds('core'), ...lessonIds('py')]);
    await planLesson(page, 'core-02').click();
    await checkExample(page, /\bprint\(/);
    const exercise = page.locator('.exercise').first();
    const hint = exercise.locator('.hint').first();
    assert.equal(await hint.count(), 0);
    await exercise.getByRole('button', { name: /أحتاج تلميحًا/ }).click();
    await hint.waitFor();
    assert.match(await hint.textContent(), /\p{Script=Arabic}/u);
    const answer = exercise.getByRole('radio').first();
    assert.equal(await answer.isDisabled(), true);
    await exercise.getByRole('link', { name: 'سجّل الدخول' }).waitFor();
  }],
  ['Web plan, common prerequisites, JavaScript and HTML examples', async (page, origin) => {
    await openPlan(page, origin, 'web');
    await checkPlan(page, [...lessonIds('core'), ...lessonIds('web')]);
    const common = planLesson(page, 'core-02');
    assert.equal((await common.getAttribute('href')).split('/')[3], 'javascript');
    await common.click();
    await checkExample(page, /\bconsole\.log\(/);

    await openPlan(page, origin, 'web');
    await planLesson(page, 'web-01').click();
    await checkExample(page, /<h1>/);
  }],
  ['Lesson return keeps the selected goal and explicit example language', async (page, origin) => {
    for (const goal of ['python', 'web']) {
      await openPlan(page, origin, goal);
      await planLesson(page, 'core-02').click();
      await checkExample(page, goal === 'web' ? /\bconsole\.log\(/ : /\bprint\(/);
      const destination = `#plan/${goal}`;
      const breadcrumb = page.locator('.breadcrumbs').getByRole('link', { name: 'خطتي التعليمية' });
      const next = page.getByRole('link', { name: 'راجع الخطوة التالية في خطتك' });
      assert.equal(await breadcrumb.getAttribute('href'), destination);
      assert.equal(await next.getAttribute('href'), destination);

      if (goal === 'web') {
        await page.getByLabel('لغة الأمثلة').selectOption('python');
        await checkExample(page, /\bprint\(/);
      }
      await next.click();
      await page.waitForURL(url => url.hash === destination);
      await page.locator('.plan-list li').first().waitFor();
      assert.equal(await page.getByLabel('ما الذي تريد استكشافه؟').inputValue(), goal);
      await planLesson(page, 'core-02').click();
      await checkExample(page, /\bprint\(/);
    }
  }],
  ['Web project starter ZIP download', async (page, origin) => {
    await visitStart(page, origin);
    await page.locator(`section[aria-labelledby="curriculum-projects"] a[href="#lesson/web-12/${release}"]`).click();
    const starter = page.getByRole('link', { name: 'نزّل ملفات البداية' });
    await starter.waitFor();
    const [download] = await Promise.all([page.waitForEvent('download'), starter.click()]);
    assert.equal(download.suggestedFilename(), 'web-starter-v1.zip');
    const archive = await readFile(await download.path());
    assert.equal(archive.subarray(0, 4).toString('hex'), '504b0304');
  }],
  ['Current Python and legacy JavaScript console labs visible to a guest', async (page, origin) => {
    await openPlan(page, origin, 'python');
    await planLesson(page, 'py-02').click();
    await checkLab(page, 'Python');

    const oldLessonPath = '/api/v1/content/phase1-ar-v1/lessons/step-by-step';
    const [oldLesson] = await Promise.all([
      page.waitForResponse(response => new URL(response.url()).pathname === oldLessonPath),
      page.goto(`${origin}/#lesson/step-by-step`),
    ]);
    assert.equal(oldLesson.status(), 200);
    await checkLab(page, 'JavaScript');
    assert.equal(await page.getByLabel('إصدار المحتوى').inputValue(), 'phase1-ar-v1');
    const breadcrumb = page.locator('.breadcrumbs').getByRole('link', { name: 'خطتي التعليمية' });
    assert.equal(await breadcrumb.getAttribute('href'), '#plan');
  }],
];

async function checkLab(page, language) {
  const lab = page.getByRole('region', { name: 'مختبر البرمجة' });
  const editor = lab.getByRole('textbox', { name: 'الكود' });
  await editor.waitFor();
  assert.equal(await lab.locator('.lab-language').textContent(), language);
  assert.equal(await lab.getByText('بيئة التشغيل غير متاحة الآن.', { exact: false }).count(), 0);
  assert.equal(await editor.getAttribute('readonly'), '');
  await lab.getByRole('link', { name: 'سجّل الدخول' }).waitFor();
}

function isReadOnlyRequest(request, origin) {
  const url = new URL(request.url());
  if (url.origin !== origin) return false;
  if (['GET', 'HEAD'].includes(request.method())) return true;

  // The guest preview endpoint reads published content and computes a plan without saving it.
  if (request.method() !== 'POST' || url.pathname !== '/api/v1/plan-previews') return false;
  const body = request.postDataJSON();
  return body?.releaseId === release && goals.includes(body.goalId);
}

async function main() {
  const url = new URL(process.env.NEXORA_BROWSER_TEST_URL || 'http://127.0.0.1:5180');
  assert.ok(['http:', 'https:'].includes(url.protocol) && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname),
    'NEXORA_BROWSER_TEST_URL must point to a loopback HTTP(S) server');
  const origin = url.origin;
  const { chromium } = require(playwright);
  const browser = await chromium.launch({ executablePath: edge, headless: true });
  let failures = 0;
  let rateLimited = 0;
  try {
    // A single guest context keeps the walkthrough within the local API rate limit.
    const context = await browser.newContext({ serviceWorkers: 'block' });
    const blocked = [];
    const errors = [];
    const throttled = [];
    await context.route('**/*', async route => {
      const request = route.request();
      if (isReadOnlyRequest(request, origin)) return route.continue();
      blocked.push(`${request.method()} ${new URL(request.url()).pathname}`);
      return route.abort();
    });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => {
      if (response.status() === 429) throttled.push(new URL(response.url()).pathname);
    });

    for (const [name, check] of checks) {
      blocked.length = 0;
      errors.length = 0;
      throttled.length = 0;
      try {
        await check(page, origin);
        assert.deepEqual(errors, [], 'Uncaught page errors');
        assert.deepEqual(blocked, [], 'Blocked browser requests');
        assert.deepEqual(throttled, [], 'Rate-limited browser requests');
        console.log(`PASSED — ${name}`);
      } catch (error) {
        if (throttled.length > 0) {
          rateLimited += 1;
          console.error(`BLOCKED — ${name}: HTTP 429 from ${[...new Set(throttled)].join(', ')}`);
        } else {
          failures += 1;
          console.error(`FAILED — ${name}\n${error.stack || error}`);
        }
      }
    }
  } finally {
    await browser.close();
  }
  console.log(`${checks.length - failures - rateLimited}/${checks.length} guest browser checks passed at ${origin}`);
  console.log('SKIPPED — Account creation, answer submission, code execution and progress persistence');
  console.log('PENDING — Observed sessions with real beginner learners');
  process.exitCode = failures || rateLimited ? 1 : 0;
}

main().catch(error => {
  console.error(`BLOCKED — ${error.stack || error}`);
  process.exitCode = 1;
});
