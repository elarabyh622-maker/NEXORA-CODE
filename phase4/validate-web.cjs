// Browser QA for the authored reference project and markup/style examples.
// Uses only a loopback server and the locally installed Edge and Playwright.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('C:/Users/BONDOK/Documents/GitHub/OmniRoute/node_modules/playwright-core');

const content = JSON.parse(fs.readFileSync(path.join(__dirname, 'content', 'web.json'), 'utf8'));
const project = content.browserProject;
const files = {
  '/index.html': ['text/html; charset=utf-8', project.html],
  '/style.css': ['text/css; charset=utf-8', project.css],
  '/app.js': ['text/javascript; charset=utf-8', project.js],
};

(async () => {
  const server = http.createServer((req, res) => {
    const file = files[new URL(req.url, 'http://127.0.0.1').pathname];
    if (!file) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'Content-Type': file[0], 'Cache-Control': 'no-store' });
    res.end(file[1]);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  let browser;
  try {
    browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
    const context = await browser.newContext({ viewport: { width: 320, height: 700 }, serviceWorkers: 'block' });
    const external = [], requested = [], errors = [];
    await context.route('**/*', async route => {
      const url = route.request().url();
      requested.push(url);
      if (!url.startsWith(origin + '/')) { external.push(url); await route.abort(); }
      else await route.continue();
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    const response = await page.goto(origin + '/index.html', { waitUntil: 'load' });
    assert.equal(response.status(), 200);
    for (const check of project.checks) {
      const element = page.locator(check.selector);
      assert.equal(await element.count(), 1, `selector ${check.selector} must be unique`);
      if (check.action === 'visible') assert.equal(await element.isVisible(), true);
      else if (check.action === 'text') assert.equal(await element.textContent(), check.value);
      else if (check.action === 'fill') await element.fill(check.value);
      else if (check.action === 'click') await element.click();
      else throw new Error(`Unknown check action: ${check.action}`);
    }
    assert.deepEqual(await page.evaluate(() => ({
      lang: document.documentElement.lang,
      dir: document.documentElement.dir,
      computedDirection: getComputedStyle(document.body).direction,
      cssLoaded: [...document.styleSheets].some(sheet => sheet.href && sheet.href.endsWith('/style.css') && sheet.cssRules.length > 0),
      background: getComputedStyle(document.body).backgroundColor,
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      linkedLabel: document.querySelector('label').control?.id,
      live: document.querySelector('#message').getAttribute('aria-live'),
    })), {lang:'ar', dir:'rtl', computedDirection:'rtl', cssLoaded:true, background:'rgb(237, 245, 243)', horizontalOverflow:false, linkedLabel:'name', live:'polite'});
    // Exercise keyboard activation separately from the supplied click checks.
    await page.locator('#name').fill('سارة');
    await page.locator('#show').focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('#message').textContent(), 'أهلاً سارة');
    await page.setViewportSize({width: 1200, height: 800});
    assert.ok(await page.locator('.card').evaluate(el => el.getBoundingClientRect().width) <= 600);
    assert.ok(requested.includes(origin + '/style.css') && requested.includes(origin + '/app.js'));
    assert.deepEqual(external, []);
    assert.deepEqual(errors, []);

    // Parse all HTML and CSS examples from the authored lessons in the browser.
    // HTML DOM assertions check the specific expected structure; CSS uses CSSOM.
    const htmlAssertions = {
      'web-01': 'h1', 'web-02': 'p > strong', 'web-03': 'html[lang="ar"][dir="rtl"] body > h1',
      'web-04': 'a[href="#about"]', 'web-12': 'label[for="name"] + input#name',
    };
    for (const [id, selector] of Object.entries(htmlAssertions)) {
      const code = content.lessons.find(x => x.id === id).examples[0].code;
      const result = await page.evaluate(({code, selector, id}) => {
        const doc = new DOMParser().parseFromString(code, 'text/html');
        const el = doc.querySelector(selector);
        return {found: !!el, listCount: id === 'web-04' ? doc.querySelectorAll('ul > li').length : null,
          linkTarget: id === 'web-04' ? !!doc.querySelector('#about') : null,
          nameControl: id === 'web-12' ? !!doc.querySelector('button#show') && !!doc.querySelector('#message[aria-live="polite"]') : null};
      }, {code, selector, id});
      assert.equal(result.found, true, `${id}: ${selector}`);
      if (id === 'web-04') { assert.equal(result.listCount, 2); assert.equal(result.linkTarget, true); }
      if (id === 'web-12') assert.equal(result.nameControl, true);
    }
    const cssExpected = {'web-05': 2, 'web-06': 1, 'web-07': 1};
    for (const [id, count] of Object.entries(cssExpected)) {
      const code = content.lessons.find(x => x.id === id).examples[0].code;
      const result = await page.evaluate(code => {
        const style = document.createElement('style'); style.textContent = code; document.head.append(style);
        const rules = [...style.sheet.cssRules].map(r => ({selector:r.selectorText, declarations:r.style.length}));
        style.remove(); return rules;
      }, code);
      assert.equal(result.length, count, `${id}: CSS rule count`);
      assert.ok(result.every(rule => rule.selector && rule.declarations > 0), `${id}: CSS declarations`);
    }
    // Parsing does not detect all HTML conformance errors; these are focused structure checks.
    console.log(`PASSED: ${project.checks.length} ordered project checks; RTL/language, loaded CSS and JS, 320px overflow, 1200px width, label/live region, keyboard activation, no external requests or page errors.`);
    console.log(`PASSED: ${Object.keys(htmlAssertions).length} HTML examples and ${Object.keys(cssExpected).length} CSS examples: focused browser DOM/CSSOM checks.`);
    console.log(`Requests: ${requested.join(', ')}`);
    await context.close();
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error('FAILED:', error.stack || error); process.exitCode = 1; });
