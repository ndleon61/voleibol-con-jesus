const assert = require('node:assert/strict');

const budgets = Object.freeze({ usableMs: 5000, firstPaintMs: 3000, initialResourcesMs: 10000, layoutShift: 0.1, images: 100 * 1024, fonts: 25 * 1024, htmlCss: 70 * 1024, javascript: 50 * 1024 });

function waitForPublicData(page, timeout = 30000) {
  return page.waitForFunction(() => {
    const content = document.getElementById('league-content');
    return content?.getAttribute('aria-busy') === 'false' && !content.hidden;
  }, null, { timeout });
}

async function navigateToUsable(page, url) {
  const start = Date.now();
  // The load event includes nonessential media; league readiness has its own stricter deadline.
  const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: budgets.usableMs });
  assert.equal(response.status(), 200);
  await waitForPublicData(page, Math.max(1, budgets.usableMs - (Date.now() - start)));
  return Date.now() - start;
}

function assertPerformance(metrics, assets) {
  assert.ok(Number.isFinite(metrics.readyMs) && metrics.readyMs <= budgets.usableMs, `Data readiness exceeds ${budgets.usableMs} ms: ${metrics.readyMs}`);
  assert.ok(Number.isFinite(metrics.firstContentfulPaintMs) && metrics.firstContentfulPaintMs <= budgets.firstPaintMs, `First paint exceeds ${budgets.firstPaintMs} ms: ${metrics.firstContentfulPaintMs}`);
  assert.ok(Number.isFinite(metrics.layoutShift) && metrics.layoutShift < budgets.layoutShift, `Unexpected layout shift: ${metrics.layoutShift}`);
  assert.ok(Number.isFinite(metrics.resourcesFinishedMs) && metrics.resourcesFinishedMs <= budgets.initialResourcesMs, `Initial resources exceed ${budgets.initialResourcesMs} ms: ${metrics.resourcesFinishedMs}`);
  assert.ok(metrics.initialImageBytes <= budgets.images, `Initial images exceed ${budgets.images} bytes`);
  assert.ok(metrics.initialFontBytes + metrics.initialIconBytes <= budgets.fonts, `Initial fonts and icons exceed ${budgets.fonts} bytes`);
  assert.ok(assets['index.html'].gzipBytes + assets['styles.css'].gzipBytes <= budgets.htmlCss);
  assert.ok(assets['app.js'].gzipBytes <= budgets.javascript);
}

module.exports = { budgets, waitForPublicData, navigateToUsable, assertPerformance };
