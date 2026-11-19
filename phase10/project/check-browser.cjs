const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');

const [origin, project, mode] = process.argv.slice(2);
const password = fs.readFileSync(0, 'utf8');
const mock = mode === 'mock';
const starterEditExercise = project === 'starter-js' && mock;
const checks = [];

async function run() {
  const browser = await chromium.launch({
    executablePath: process.env.BROWSER_EXECUTABLE || undefined,
    headless: true,
  });
  try {
    const page = await browser.newPage({ viewport: { width: 375, height: 812 }, locale: 'ar-EG' });
    page.setDefaultTimeout(10000);
    const errors = [];
    const responses = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => {
      const url = new URL(response.url());
      if (url.pathname.startsWith('/api/')) {
        assert.equal(url.origin, origin);
        responses.push([response.request().method(), url.pathname, response.status()]);
      }
    });
    // Observe signals actually received by the in-memory adapter without altering their behavior.
    await page.addInitScript(() => {
      window.mockListSignals = [];
      const check = AbortSignal.prototype.throwIfAborted;
      AbortSignal.prototype.throwIfAborted = function () {
        window.mockListSignals.push(this);
        return check.call(this);
      };
    });
    const button = name => page.getByRole('button', { name, exact: true });
    const input = name => page.getByLabel(name, { exact: true });
    const title = name => page.getByRole('heading', { name, exact: true });
    const rows = page.locator('ul.products li');
    const empty = page.getByText('لا توجد منتجات تطابق البحث.', { exact: true });
    const name = 'منتج تجربة';
    const category = 'فئة تجربة';
    const row = rows.filter({ has: title(name) });
    const search = async (q, cat) => {
      await input('ابحث بالاسم').fill(q);
      await input('التصنيف الكامل').fill(cat);
      const responded = mock ? Promise.resolve() : page.waitForResponse(response => {
        const url = new URL(response.url());
        return url.pathname === '/api/products' && url.searchParams.get('q') === q.trim() &&
          url.searchParams.get('category') === cat.trim();
      }).then(response => response.finished());
      await Promise.all([responded, button('بحث').click()]);
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    };
    const login = async role => {
      await input('اسم المستخدم').fill(role);
      await input('كلمة المرور').fill(password);
      await button('تسجيل الدخول').click();
      await page.getByText(role + ' · ' + (role === 'admin' ? 'مسؤول' : 'قارئ'), { exact: true }).waitFor();
    };
    const logout = async () => {
      await button('تسجيل الخروج').click();
      await input('اسم المستخدم').waitFor();
      await page.getByText('تم تسجيل الخروج.', { exact: true }).waitFor();
    };
    const create = async () => {
      for (const [label, value] of [['اسم المنتج', name], ['تصنيف المنتج', category],
                                    ['السعر بالقروش', '0'], ['الكمية المتاحة', '0']]) {
        await input(label).fill(value);
      }
      await button('حفظ المنتج').click();
      await row.waitFor();
    };
    const readonly = async () => {
      assert.equal(await title('إضافة منتج').count(), 0);
      assert.equal(await page.getByRole('button', { name: /^(تعديل |حذف )/ }).count(), 0);
    };
    const zeroPrice = await page.evaluate(() =>
      new Intl.NumberFormat('ar-EG', { style: 'currency', currency: 'EGP' }).format(0));

    await page.goto(origin);
    await title('كتالوج المنتجات').waitFor();
    if (mock) {
      await title('دفتر رسم').waitFor();
      assert.equal(await rows.count(), 2);
      const flags = await page.evaluate(() => window.mockListSignals.map(signal => signal.aborted));
      assert.deepEqual(flags, [true, false]);
      checks.push('React development StrictMode unmount aborts first list, remount keeps current list');
    } else {
      await empty.waitFor();
      assert.equal(await page.getByText('training', { exact: true }).count(), 0);
    }
    await readonly();
    assert.ok(await page.evaluate(() => document.dir === 'rtl' && document.documentElement.scrollWidth <= innerWidth));
    checks.push('anonymous mobile RTL list and read-only controls');

    await input('اسم المستخدم').fill('reader');
    await input('كلمة المرور').fill('invalid-test-entry');
    await button('تسجيل الدخول').click();
    await page.getByRole('alert').waitFor();
    assert.equal(await input('كلمة المرور').inputValue(), '');
    checks.push('unsuccessful login reports error and clears password');
    await login('reader');
    await readonly();
    await logout();
    assert.equal(await input('كلمة المرور').inputValue(), '');
    checks.push('reader can sign in, read and log out with no management controls');

    await login('admin');
    await search('لا يوجد هنا', '');
    await empty.waitFor();
    await create();
    assert.equal(await row.locator('strong').textContent(), zeroPrice);
    await row.getByText(category + ' · المخزون 0', { exact: true }).waitFor();
    assert.equal(await input('ابحث بالاسم').inputValue(), '');
    assert.equal(await input('التصنيف الكامل').inputValue(), '');
    checks.push('admin creates item with zero price and stock and active filters reset');

    await search('  تجربة  ', '  ' + category + '  ');
    await row.waitFor();
    assert.equal(await rows.count(), 1);
    await search('تجربة', 'فئة');
    await empty.waitFor();
    await search('تجربة', category);
    await row.waitFor();
    checks.push('trimmed combined name and exact category filter, empty state and recovery');

    await button('تعديل ' + name).click();
    await input('اسم المنتج').fill('تغيير ملغى');
    await button('إلغاء التعديل').click();
    await title('إضافة منتج').waitFor();
    assert.equal(await input('اسم المنتج').inputValue(), '');
    await row.waitFor();
    checks.push('cancel editing discards draft');
    await button('تعديل ' + name).click();
    await input('الكمية المتاحة').fill('3');
    await button('حفظ المنتج').click();
    await title('إضافة منتج').waitFor();
    await row.getByText(category + ' · المخزون ' + (starterEditExercise ? 0 : 3), { exact: true }).waitFor();
    checks.push(starterEditExercise ? 'documented JS starter exercise leaves edited stock unchanged' : 'saved edit updates displayed stock');

    await button('حذف ' + name).click();
    await page.getByText('هل تريد حذف ' + name + '؟', { exact: true }).waitFor();
    await button('إلغاء الحذف').click();
    assert.equal(await button('تأكيد الحذف').count(), 0);
    await row.waitFor();
    checks.push('named delete confirmation can be cancelled');

    if (!mock) {
      // Hold a completed fetch before React receives it, as can happen with async decoding.
      // The real HTTP request completes; the app must ignore it once a newer query wins.
      // The adapter captured fetch at mount. Install the delay before a fresh navigation.
      await page.addInitScript(() => {
        const original = window.fetch.bind(window);
        window.fetch = async (url, options) => {
          const response = await original(url, options);
          if (new URL(url, location.href).searchParams.get('q') === 'obsolete') {
            window.olderSignal = options.signal;
            await new Promise(resolve => { window.releaseOlder = resolve; });
            window.olderReturned = true;
          }
          return response;
        };
      });
    }
    assert.deepEqual(await page.evaluate(() => [localStorage.length, sessionStorage.length, document.cookie]), [0, 0, '']);
    await page.reload();
    await input('اسم المستخدم').waitFor();
    if (mock) {
      await title('دفتر رسم').waitFor();
      assert.equal(await row.count(), 0);
    } else {
      await row.waitFor();
    }
    await readonly();
    checks.push(mock ? 'refresh clears in-memory token and restores demo seed' : 'refresh clears token and preserves SQLite product');

    if (mock) {
      await search('حقيبة', '');
      await search('دفتر', 'قرطاسية');
      await title('دفتر رسم').waitFor();
      assert.equal(await rows.count(), 1);
      const flags = await page.evaluate(() => window.mockListSignals.map(signal => signal.aborted));
      assert.ok(flags.length >= 4 && flags.slice(0, -1).every(Boolean) && !flags.at(-1));
      checks.push('repeated searches abort all obsolete mock list signals');
    } else {
      await search('obsolete', '');
      await page.waitForFunction(() => !!window.releaseOlder);
      await page.getByText('جارٍ تحميل المنتجات…').waitFor();
      await search('تجربة', category);
      await row.waitFor();
      assert.ok(await page.evaluate(() => window.olderSignal.aborted));
      await page.evaluate(async () => {
        window.releaseOlder();
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      });
      assert.ok(await page.evaluate(() => window.olderReturned));
      await row.waitFor();
      assert.equal(await rows.count(), 1);
      checks.push('in-flight obsolete API result arrives last after abort and preserves newer results');
      await page.route('**/api/products?**', route => route.fulfill({
        status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'temporary test error' }),
      }), { times: 1 });
      await button('بحث').click();
      await page.getByRole('alert').filter({ hasText: 'temporary test error' }).waitFor();
      assert.equal(await rows.count(), 0);
      await button('بحث').click();
      await row.waitFor();
      checks.push('current API error removes stale list, unchanged search retries successfully');
    }

    await login('admin');
    if (mock) await create();
    await button('حذف ' + name).click();
    await button('تأكيد الحذف').click();
    await page.getByText('تم حذف المنتج.', { exact: true }).waitFor();
    if (mock) await title('دفتر رسم').waitFor();
    else await empty.waitFor();
    assert.equal(await row.count(), 0);
    await logout();
    checks.push('confirmed deletion removes item and admin logs out');
    if (mock) {
      assert.equal(responses.length, 0);
    } else {
      for (const [method, path, status] of [['POST', '/api/login', 401], ['POST', '/api/login', 200],
          ['GET', '/api/me', 200], ['GET', '/api/products', 200], ['POST', '/api/products', 201],
          ['PUT', '/api/products/1', 200], ['DELETE', '/api/products/1', 204], ['POST', '/api/logout', 204]]) {
        assert.ok(responses.some(r => r[0] === method && r[1] === path && r[2] === status), method + ' ' + path);
      }
      checks.push('same-origin real API login, me, CRUD and bodyless 204 responses observed');
    }
    assert.deepEqual(errors, []);
    checks.push('no uncaught browser errors');
    console.log(JSON.stringify({ project, mode, browser: browser.version(), viewport: '375x812', checks }));
  } finally {
    await browser.close();
  }
}
run().catch(error => {
  const diagnostic = String(error.stack || error);
  console.error(password ? diagnostic.replaceAll(password, '[redacted]') : diagnostic);
  process.exitCode = 1;
});
