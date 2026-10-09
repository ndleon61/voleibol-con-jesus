// Optional browser QA: NODE_PATH=/path/to/playwright/node_modules node tests/public-browser.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');
const { chromium, webkit } = require('playwright');

const base = process.env.PUBLIC_QA_URL || 'http://127.0.0.1:3002';
const output = process.env.PUBLIC_QA_OUTPUT || '/private/tmp/voli-phase9a-qa';
const widths = [320, 360, 375, 390, 430, 768, 1024, 1440];
const report = { viewports: [], slow3g: [], scenarios: [], assets: {}, limitations: [] };
const selectLines = new Set(fs.readFileSync('index.html', 'utf8').split('\n').flatMap((line, index) => line.includes('<select ') ? [index] : []));
fs.mkdirSync(output, { recursive: true });

async function ready(page) {
  await page.waitForFunction(() => document.getElementById('league-content').getAttribute('aria-busy') === 'false' && !document.getElementById('league-content').hidden);
}

async function overflow(page, width, label) {
  const size = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
  assert.ok(size.document <= size.viewport + 1, `${label}: horizontal overflow at ${width}: ${JSON.stringify(size)}`);
}

async function actualViewports(browser, name) {
  for (const width of widths) {
    const page = await browser.newPage({ viewport: { width, height: 844 }, reducedMotion: 'reduce', isMobile: width < 600, hasTouch: width < 600 });
    const errors = [], external = [], nativeSelectWarnings = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
      if (!/Content Security Policy|Refused to/.test(message.text())) return;
      const location = message.location();
      // Reproduced with a bare native <select> and strict CSP, without any site JS/CSS.
      if (name === 'webkit' && location.url === base + '/' && selectLines.has(location.lineNumber) &&
          message.text().startsWith('Refused to apply a stylesheet')) nativeSelectWarnings.push(message.text());
      else errors.push(message.text());
    });
    page.on('request', request => { if (new URL(request.url()).origin !== base) external.push(request.url()); });
    const response = await page.goto(base);
    assert.equal(response.status(), 200);
    assert.ok(response.headers()['content-security-policy'].includes("script-src 'self'"));
    await ready(page);
    await overflow(page, width, 'real data');
    assert.equal(await page.locator('.team-card').count(), 5);
    assert.equal(await page.locator('#results .match-card').count(), 2);
    assert.equal(await page.locator('#standings tr').count(), 5);
    assert.equal(await page.locator('#menu-toggle').count(), 0);
    assert.equal(await page.locator('#main-nav').isVisible(), width >= 1024);
    assert.equal(await page.locator('.hero-slogan').textContent(), 'La pasión se vive en la cancha.');
    assert.equal(await page.locator('.tournament-band .featured-match').count(), 0);
    assert.equal(await page.locator('.calendar-link').getAttribute('href'), '#partidos');
    if (width < 1024) {
      assert.equal(await page.locator('#bottom-nav').isVisible(), true);
      assert.equal(await page.locator('#bottom-nav a').count(), 4);
      for (const anchor of await page.locator('#bottom-nav a').all()) {
        const box = await anchor.boundingBox();
        assert.ok(box.width >= 44 && box.height >= 44, 'bottom tabs must remain touch-friendly');
      }
      await page.locator('#bottom-nav a[href="#clasificacion"]').click();
      assert.equal(await page.locator('#bottom-nav a[href="#clasificacion"]').getAttribute('aria-current'), 'location');
      await page.locator('#bottom-nav a[href="#inicio"]').click();
      await page.locator('footer a').scrollIntoViewIfNeeded();
      const footerBottom = await page.locator('footer a').evaluate(element => element.getBoundingClientRect().bottom);
      const barTop = await page.locator('#bottom-nav').evaluate(element => element.getBoundingClientRect().top);
      assert.ok(footerBottom <= barTop, 'last page control must not be covered by the bottom bar');
    } else {
      assert.equal(await page.locator('#bottom-nav').isVisible(), false);
    }
    if (width < 600) {
      await page.locator('#standings-details').click();
      await overflow(page, width, 'expanded standings');
      await page.locator('#standings-details').click();
    }
    await page.locator('#results summary').first().click();
    await page.locator('#teams summary').first().click();
    await overflow(page, width, 'expanded details');
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    // WebKit rejects Playwright's screenshot-only "body {}" synchronization style.
    // Check the application's CSP before the harness attempts to inject that style.
    await page.screenshot({ path: path.join(output, `${name}-${width}.png`), fullPage: true });
    report.viewports.push({ engine: name, width, overflow: false, scriptOrCspErrors: 0, nativeSelectWarnings: nativeSelectWarnings.length, screenshotHarnessWarnings: errors.length });
    await page.close();
  }
}

function mockData(id) {
  const historical = id === 2;
  const name = historical ? 'Los Abusadores · nombre histórico' : 'EquipoConUnNombreExtraordinariamenteLargo'.repeat(2);
  const logo = historical ? '/team-logos/' + 'a'.repeat(32) + '.webp' : '/media/los_lobos.JPG';
  return {
    teams: [{ id: 1, name, logo }, { id: 2, name: '<img src=x onerror="window.injected=true">', logo: 'https://invalid.test/logo.png' }],
    jornadas: [{ number: 8, games: [
      { id: 1, team1Id: 1, team2Id: 2, team1: name, team2: 'Sin logotipo', team1Logo: logo, team2Logo: '', status: 'scheduled', startsAt: '2099-07-16T00:00:00Z' },
      { id: 2, team1Id: 1, team2Id: 2, team1: name, team2: 'Sin logotipo', team1Logo: logo, team2Logo: '', status: 'finished', startsAt: '2026-07-16T00:00:00Z', results: { sets: [25, 25, 25].map((points, i) => ({ setNumber: i + 1, team1Points: points, team2Points: 20 })) } },
    ] }],
    standings: [{ teamId: 1, team: name, logo, wins: 1, losses: 0, setsWon: 3, setsLost: 0 }, { teamId: 2, team: 'Sin logotipo', logo: '', wins: 0, losses: 1, setsWon: 0, setsLost: 3 }],
  };
}

async function scenarios(browser) {
  const page = await browser.newPage({ viewport: { width: 320, height: 844 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    const seasons = [{ id: 1, name: 'Temporada 2026' }, { id: 2, name: 'Temporada 2025' }];
    const tournaments = [{ id: 1, name: 'Torneo de pruebas actual', seasonId: 1, status: 'active', isPublic: true }, { id: 2, name: 'Torneo histórico de pruebas', seasonId: 2, status: 'archived', isPublic: false }];
    const match = url.pathname.match(/^\/api\/tournaments\/(\d+)\/(teams|jornadas|standings)$/);
    const data = url.pathname === '/api/seasons' ? seasons : url.pathname === '/api/tournaments' ? tournaments : mockData(Number(match?.[1]))[match?.[2]];
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.route('**/team-logos/**', route => route.abort());
  await page.goto(base); await ready(page);
  assert.equal(await page.locator('#featured-match .match-card').count(), 1);
  assert.ok((await page.locator('#results').innerText()).includes('3–0'));
  assert.equal(await page.evaluate(() => window.injected), undefined);
  for (const width of widths) {
    await page.setViewportSize({ width, height: 844 });
    await overflow(page, width, 'long names and featured match');
    if (width < 600) { await page.locator('#standings-details').click(); await overflow(page, width, 'long names with full statistics'); await page.locator('#standings-details').click(); }
    await page.screenshot({ path: path.join(output, `fixture-${width}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.selectOption('#season-select', '2');
  await page.selectOption('#tournament-select', '2');
  await page.waitForFunction(() => document.getElementById('tournament-name').textContent === 'Torneo histórico de pruebas' && document.getElementById('league-content').getAttribute('aria-busy') === 'false');
  assert.match(await page.locator('#teams').innerText(), /nombre histórico/);
  assert.match(await page.locator('#history-status').innerText(), /históricos/);
  await page.locator('#equipos').scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  assert.equal(await page.locator('#teams img').count(), 0, 'failed historical logos must leave initials');
  await page.locator('#current-tournament').click(); await ready(page);
  assert.match(await page.locator('#tournament-name').innerText(), /actual/);
  await page.route('**/api/tournaments/1/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.locator('#refresh-data').click(); await ready(page);
  assert.match(await page.locator('#teams').innerText(), /No hay equipos/);
  assert.match(await page.locator('#results').innerText(), /Todavía no hay resultados/);
  assert.deepEqual(errors, []);
  report.scenarios.push('featured future match', 'long names at all widths', 'escaping', 'missing and failed logos', 'historical snapshots', 'season/tournament selectors', 'return to active tournament', 'empty responses');
  await page.close();

  const retry = await browser.newPage({ viewport: { width: 390, height: 844 } });
  let fail = true;
  await retry.route('**/api/**', route => fail ? route.fulfill({ status: 503, body: '{}' }) : route.continue());
  await retry.goto(base);
  await retry.locator('#error-notice').waitFor({ state: 'visible' });
  assert.equal(await retry.locator('#league-content').isVisible(), false);
  fail = false;
  await retry.locator('#retry-data').click(); await ready(retry);
  assert.equal(await retry.locator('#error-notice').isVisible(), false);
  await retry.route('**/media/**', route => route.abort());
  await retry.locator('#refresh-data').click(); await ready(retry);
  assert.equal(await retry.locator('.team-card').count(), 5);
  report.scenarios.push('503 and working retry', 'unavailable images do not block results');
  await retry.close();
}

async function slow3g(browser) {
  for (let run = 1; run <= 3; run++) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const page = await context.newPage();
    await page.addInitScript(() => {
      window.publicQACls = 0;
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) if (!entry.hadRecentInput) window.publicQACls += entry.value;
      }).observe({ type: 'layout-shift', buffered: true });
    });
    const session = await context.newCDPSession(page);
    await session.send('Network.enable');
    await session.send('Network.setCacheDisabled', { cacheDisabled: true });
    await session.send('Network.emulateNetworkConditions', { offline: false, latency: 400, downloadThroughput: 50000, uploadThroughput: 50000, connectionType: 'cellular3g' });
    await session.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    let wireBytes = 0;
    session.on('Network.loadingFinished', event => { wireBytes += event.encodedDataLength; });
    const start = Date.now();
    await page.goto(base); await ready(page);
    const readyMs = Date.now() - start;
    await page.waitForTimeout(1000);
    const entries = await page.evaluate(() => performance.getEntriesByType('resource').map(entry => ({ name: entry.name, bytes: entry.encodedBodySize, transfer: entry.transferSize })));
    const images = entries.filter(entry => /\.(webp|JPG)$/.test(entry.name)).reduce((sum, entry) => sum + entry.bytes, 0);
    const metrics = await page.evaluate(() => ({ firstContentfulPaintMs: performance.getEntriesByName('first-contentful-paint')[0]?.startTime, layoutShift: window.publicQACls }));
    report.slow3g.push({ run, readyMs, wireBytes, initialImageBytes: images, requests: entries.length + 1, ...metrics });
    assert.ok(images <= 100 * 1024);
    assert.ok(metrics.layoutShift < 0.1, `Unexpected initial layout shift: ${metrics.layoutShift}`);
    await page.screenshot({ path: path.join(output, `slow3g-${run}.png`) });
    await context.close();
  }
}

(async () => {
  for (const asset of ['index.html', 'styles.css', 'app.js']) {
    const data = fs.readFileSync(asset);
    const response = await fetch(`${base}/${asset === 'index.html' ? '' : asset}`);
    report.assets[asset] = { bytes: data.length, gzipBytes: zlib.gzipSync(data, { level: 9 }).length, servedEncoding: response.headers.get('content-encoding') || 'identity', cacheControl: response.headers.get('cache-control') };
  }
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  try { await actualViewports(browser, 'chromium'); await scenarios(browser); await slow3g(browser); }
  finally { await browser.close(); }
  let safari;
  try { safari = await webkit.launch(); }
  catch (error) { report.limitations.push('WebKit unavailable: install the optional Playwright WebKit browser to verify Safari engine compatibility.'); }
  if (safari) {
    try { await actualViewports(safari, 'webkit'); await scenarios(safari); }
    finally { await safari.close(); }
  }
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
