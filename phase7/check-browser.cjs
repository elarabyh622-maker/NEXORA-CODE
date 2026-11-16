const assert = require('node:assert/strict');

const edge = process.env.NEXORA_EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const playwright = process.env.NEXORA_PLAYWRIGHT_CORE ||
  'C:/Users/BONDOK/Documents/GitHub/OmniRoute/node_modules/playwright-core';
const origin = (process.env.NEXORA_PHASE7_BROWSER_URL || 'http://127.0.0.1:5197').replace(/\/$/, '');
const release = 'phase7-ar-v1';

async function verify() {
  const { chromium } = require(playwright);
  const browser = await chromium.launch({ executablePath: edge, headless: true });
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(20000);
    await page.goto(origin + '/#start');
    await page.locator('#start-goals').waitFor();
    const specialization = page.locator('a[href="#plan/data-analysis"]');
    await specialization.getByRole('heading', { name: /تحليل البيانات/ }).waitFor();
    await specialization.click();
    const steps = page.locator('.plan-list .plan-step a');
    await steps.first().waitFor();
    assert.equal(await steps.count(), 32);
    assert.match(await steps.nth(23).getAttribute('href'), /#lesson\/py-12\//);
    const firstDataLesson = steps.nth(24);
    assert.match(await firstDataLesson.getAttribute('href'), /#lesson\/data-01\//);
    await firstDataLesson.click();
    await page.locator('.example pre code').first().waitFor();
    assert.match(await page.locator('.example pre code').first().textContent(), /csv/);
    await page.getByRole('link', { name: 'راجع الخطوة التالية في خطتك' }).click();
    await page.waitForURL(origin + '/#plan/data-analysis');
    const capstone = page.locator(`.plan-list a[href^="#lesson/data-08/${release}"]`);
    await capstone.click();
    await page.getByRole('heading', { name: 'مختبر البرمجة' }).waitFor();
    await page.locator('.code-lab textarea').first().waitFor();
    console.log('PASSED: Edge specialization card, 32-step plan, Python example, contextual return and capstone lab.');
  } finally {
    await browser.close();
  }
}

verify().catch(error => { console.error(error); process.exitCode = 1; });
