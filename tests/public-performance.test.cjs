const assert = require('node:assert/strict');
const test = require('node:test');
const { budgets, navigateToUsable, assertPerformance } = require('./public-performance.cjs');
const assets = { 'index.html': { gzipBytes: 3125 }, 'styles.css': { gzipBytes: 3760 }, 'app.js': { gzipBytes: 6220 } };
const metrics = { readyMs: 2700, firstContentfulPaintMs: 1600, resourcesFinishedMs: 3800, layoutShift: 0.001, initialImageBytes: 21830, initialFontBytes: 0, initialIconBytes: 554 };

test('Slow 3G readiness does not wait for unrelated media or extend its deadline', async () => {
  const calls = [];
  const page = {
    goto: async (_, options) => { calls.push(options); return { status: () => 200 }; },
    waitForFunction: async (_, arg, options) => { calls.push(options); },
  };
  await navigateToUsable(page, 'http://localhost');
  assert.equal(calls[0].waitUntil, 'domcontentloaded');
  assert.equal(calls[0].timeout, budgets.usableMs);
  assert.ok(calls[1].timeout <= budgets.usableMs);
});

test('Slow 3G rejects slow readiness, missing paint, layout shift and excessive transfer', () => {
  assertPerformance(metrics, assets);
  for (const change of [{ readyMs: 5001 }, { firstContentfulPaintMs: 3001 }, { firstContentfulPaintMs: undefined }, { resourcesFinishedMs: 10001 }, { layoutShift: 0.1 }, { initialImageBytes: 102401 }, { initialFontBytes: 25601 }, { initialIconBytes: 25601 }]) {
    assert.throws(() => assertPerformance({ ...metrics, ...change }, assets));
  }
  assert.throws(() => assertPerformance(metrics, { ...assets, 'app.js': { gzipBytes: 51201 } }));
  assert.throws(() => assertPerformance(metrics, { ...assets, 'styles.css': { gzipBytes: 71681 } }));
});
