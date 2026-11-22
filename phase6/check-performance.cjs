const assert = require('node:assert/strict');

const executablePath = process.env.NEXORA_EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const playwright = process.env.NEXORA_PLAYWRIGHT_CORE ||
  'C:/Users/BONDOK/Documents/GitHub/OmniRoute/node_modules/playwright-core';
const target = new URL(process.env.NEXORA_PERF_TARGET || 'https://desktop-phkhegp.tail3372f6.ts.net:10000/nexora-commercial/');
const scenario = process.env.NEXORA_PERF_PAGE || 'home';
const warm = process.env.NEXORA_PERF_WARM === '1';
const count = Number(process.env.NEXORA_PERF_RUNS || (warm ? 1 : 3));
const observeHeaders = ['cache-control', 'content-encoding', 'content-length', 'content-type', 'etag', 'last-modified', 'vary'];
const profiles = {
  desktop: { viewport: { width: 1365, height: 900 }, deviceScaleFactor: 1 },
  mobile: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
};

function median(values) {
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 === 0 ? (ordered[middle - 1] + ordered[middle]) / 2 : ordered[middle];
}

function collectPaints() {
  window.nexoraPerf = { lcp: 0, cls: 0, longTask: 0, shifts: [] };
  let shiftWindow;
  for (const type of ['largest-contentful-paint', 'layout-shift', 'longtask']) {
    new PerformanceObserver(list => {
      for (const entry of list.getEntries()) {
        if (type === 'largest-contentful-paint') {
          window.nexoraPerf.lcp = entry.startTime;
        } else if (type === 'longtask') {
          window.nexoraPerf.longTask += Math.max(entry.duration - 50, 0);
        } else if (!entry.hadRecentInput) {
          if (!shiftWindow || entry.startTime - shiftWindow.last > 1000 || entry.startTime - shiftWindow.start > 5000) {
            shiftWindow = { start: entry.startTime, last: entry.startTime, sum: 0 };
          }
          shiftWindow.last = entry.startTime;
          shiftWindow.sum += entry.value;
          window.nexoraPerf.cls = Math.max(window.nexoraPerf.cls, shiftWindow.sum);
          window.nexoraPerf.shifts.push({
            time: Math.round(entry.startTime),
            value: entry.value,
            sources: entry.sources.map(({ node, previousRect, currentRect }) => ({
              tag: node?.nodeName,
              className: typeof node?.className === 'string' ? node.className : undefined,
              previousTop: Math.round(previousRect.y),
              currentTop: Math.round(currentRect.y),
            })),
          });
        }
      }
    }).observe({ type, buffered: true });
  }
}

function collectNavigation() {
  const nav = performance.getEntriesByType('navigation')[0];
  const fcp = performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? 0;
  const resources = performance.getEntriesByType('resource').map(entry => ({
    path: new URL(entry.name).pathname,
    kind: entry.initiatorType,
    start: Math.round(entry.startTime),
    duration: Math.round(entry.duration),
    transferBytes: entry.transferSize,
    encodedBytes: entry.encodedBodySize,
    decodedBytes: entry.decodedBodySize,
    cacheDelivery: entry.deliveryType,
  }));
  return {
    ttfb: nav.responseStart,
    fcp,
    ...window.nexoraPerf,
    bytes: resources.reduce((total, resource) => total + resource.transferBytes, nav.transferSize),
    networkTransfers: resources.filter(resource => resource.transferBytes > 0).length + Number(nav.transferSize > 0),
    resources,
  };
}

async function navigate(page) {
  const response = await page.goto(target.href, { waitUntil: 'domcontentloaded' });
  assert.equal(response?.status(), 200, 'The benchmark page must load successfully');
  if (scenario === 'auth') {
    await page.locator('#auth-heading').waitFor({ state: 'visible' });
  } else {
    await page.locator('#access-heading').waitFor({ state: 'visible' });
    await page.locator('.offer-list li').first().waitFor({ state: 'visible' });
  }
  const ready = await page.evaluate(() => performance.now());
  await page.waitForLoadState('load');
  if (scenario === 'auth') await page.waitForFunction(() => [...document.querySelectorAll('main img')].every(image => image.complete && image.naturalWidth));
  await page.waitForFunction(() => document.fonts.status === 'loaded');
  await page.waitForTimeout(350);
  return ready;
}

async function measure(browser, profile) {
  const context = await browser.newContext({ ...profiles[profile], serviceWorkers: 'block' });
  try {
    const page = await context.newPage();
    page.setDefaultTimeout(45000);
    await page.addInitScript(collectPaints);
    if (profile === 'mobile') {
      const session = await context.newCDPSession(page);
      await session.send('Network.enable');
      await session.send('Emulation.setCPUThrottlingRate', { rate: 4 });
      await session.send('Network.emulateNetworkConditions', {
        offline: false, latency: 150, downloadThroughput: 1600000 / 8, uploadThroughput: 750000 / 8, connectionType: 'cellular3g',
      });
    }

    const responses = [];
    page.on('response', response => {
      const headers = response.headers();
      responses.push({
        path: new URL(response.url()).pathname,
        status: response.status(),
        headers: Object.fromEntries(observeHeaders.filter(name => name in headers).map(name => [name, headers[name]])),
      });
    });
    let ready = await navigate(page);
    if (warm) {
      await page.goto('about:blank');
      responses.length = 0;
      ready = await navigate(page);
    }
    const metrics = await page.evaluate(collectNavigation);
    return { ...metrics, ready, requests: responses.length, responses };
  } finally {
    await context.close();
  }
}

async function main() {
  assert.ok(['http:', 'https:'].includes(target.protocol) && !target.username && !target.password, 'Expected an HTTP(S) benchmark URL without credentials');
  assert.ok(['home', 'auth'].includes(scenario), 'NEXORA_PERF_PAGE must be home or auth');
  assert.ok(Number.isInteger(count) && count >= 1 && count <= 5, 'NEXORA_PERF_RUNS must be an integer from 1 to 5');
  target.hash = scenario === 'auth' ? 'auth' : '';
  const { chromium } = require(playwright);
  const browser = await chromium.launch({ executablePath, headless: true });
  try {
    for (const profile of Object.keys(profiles)) {
      const results = [];
      for (let run = 1; run <= count; run++) {
        const result = await measure(browser, profile);
        results.push(result);
        const { shifts, resources, responses, ...metrics } = result;
        console.log(JSON.stringify({ scenario, cache: warm ? 'warm' : 'cold', profile, run, metrics,
          ...(run === 1 ? { shifts, resources, responses } : {}) }));
      }
      const keys = ['ttfb', 'fcp', 'lcp', 'cls', 'longTask', 'ready', 'bytes', 'requests', 'networkTransfers'];
      const medians = Object.fromEntries(keys.map(key => [key, +median(results.map(result => result[key])).toFixed(key === 'cls' ? 4 : 0)]));
      console.log(JSON.stringify({ scenario, cache: warm ? 'warm' : 'cold', profile, medians }));
    }
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
