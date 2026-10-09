// Optional visual QA; APIs are intercepted, so no administrator or league data is changed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium, webkit } = require('playwright');
const base = process.env.ADMIN_QA_URL || 'http://127.0.0.1:3002';
const output = process.env.ADMIN_QA_OUTPUT || '/private/tmp/voli-admin-qa';
const template = fs.readFileSync('admin.html', 'utf8').replaceAll('{{ csrf_token }}', 'qa-csrf');
const teams = [
  { id: 1, name: 'La Furia Roja', logo: '/media/preview-la_furia_roja.webp' },
  { id: 2, name: 'Los Lobos', logo: '/media/preview-los_lobos.webp' },
  { id: 3, name: 'EquipoConUnNombreExtraordinariamenteLargo'.repeat(2), logo: '' },
];
const sets = [1, 2, 3].map(setNumber => ({ setNumber, team1Points: 25, team2Points: 10 }));
const jornadas = [{ id: 1, number: 1, games: [
  { id: 1, team1Id: 1, team2Id: 2, team1: teams[0].name, team2: teams[1].name, status: 'scheduled', startsAt: '2099-07-16T00:00:00Z', date: '2099-07-15', time: '20:00', results: { sets: [] } },
  { id: 2, team1Id: 1, team2Id: 2, team1: teams[0].name, team2: teams[1].name, status: 'finished', startsAt: '2026-07-16T00:00:00Z', date: '2026-07-15', time: '20:00', results: { sets } },
] }];
const standings = teams.map((team, i) => ({ teamId: team.id, team: team.name, wins: i ? 0 : 1, losses: i === 1 ? 1 : 0, setsWon: i ? 0 : 3, setsLost: i === 1 ? 3 : 0 }));

function fixture(url) {
  if (url.endsWith('/stats')) return { teams: 3, jornadas: 1, matches: 2 };
  if (url.endsWith('/seasons')) return [{ id: 1, name: 'Temporada 2026', status: 'active' }];
  if (url.endsWith('/tournaments')) return [{ id: 1, seasonId: 1, name: 'Torneo de la liga', status: 'active', isPublic: true }];
  if (url.endsWith('/standings')) return standings;
  if (url.endsWith('/jornadas')) return jornadas;
  if (url.endsWith('/teams')) return url.includes('/tournaments/') ? teams.slice(0, 2) : teams;
  throw new Error(`Unexpected fixture request: ${url}`);
}

async function overflow(page) {
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  for (const [name, engine] of [['chromium', chromium], ['webkit', webkit]]) {
    const browser = await engine.launch(name === 'chromium' ? { executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' } : {});
    try {
      for (const width of [320, 390, 768, 1024, 1440]) {
        const page = await browser.newPage({ viewport: { width, height: 844 }, reducedMotion: 'reduce' });
        const errors = [], writes = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.route('**/admin.html', route => route.fulfill({ contentType: 'text/html', body: template }));
        // These assets are also authenticated in Flask; serve source only inside this isolated fixture.
        for (const file of ['admin.js', 'scheduling.js', 'competitions.js']) {
          await page.route(`**/${file}`, route => route.fulfill({ contentType: 'application/javascript', body: fs.readFileSync(file, 'utf8') }));
        }
        await page.route('**/api/**', route => {
          const request = route.request();
          if (request.method() !== 'GET') {
            writes.push({ method: request.method(), path: new URL(request.url()).pathname, csrf: request.headers()['x-csrf-token'] });
            return route.fulfill({ json: { message: 'Resultado guardado correctamente.' } });
          }
          return route.fulfill({ json: fixture(new URL(request.url()).pathname) });
        });
        await page.goto(base + '/admin.html');
        try {
          await page.waitForFunction(() => document.querySelectorAll('.admin-team-row').length === 3 && document.querySelector('#competition-message').textContent === '' && document.querySelector('#schedule-message').textContent === '');
        } catch (error) {
          console.error(await page.evaluate(() => [...document.querySelectorAll('[role="status"]')].map(e => [e.id, e.textContent])), errors);
          throw error;
        }
        await overflow(page);
        assert.equal(await page.locator('#admin-nav a').count(), 5);
        for (const link of await page.locator('#admin-nav a').all()) {
          const box = await link.boundingBox();
          assert.ok(box.width >= 44 && box.height >= 44);
        }
        await page.screenshot({ path: path.join(output, `${name}-${width}-panel.png`), fullPage: false });
        await page.locator('#admin-nav a[href="#team-management"]').click();
        await page.waitForFunction(() => document.querySelector('#admin-nav a[href="#team-management"]').getAttribute('aria-current') === 'location');
        assert.equal(await page.locator('#admin-nav a[href="#team-management"]').getAttribute('aria-current'), 'location');
        await page.getByRole('button', { name: `Editar ${teams[0].name}`, exact: true }).click();
        assert.equal(await page.locator('#team-name').inputValue(), teams[0].name);
        assert.equal(await page.locator('#team-current-logo').isVisible(), true);
        await page.locator('#cancel-team-edit').click();
        await page.getByRole('button', { name: `Eliminar ${teams[0].name}`, exact: true }).click();
        assert.equal(await page.locator('#delete-team-dialog').isVisible(), true);
        await page.screenshot({ path: path.join(output, `${name}-${width}-dialog.png`) });
        await page.locator('#cancel-team-delete').click();
        await overflow(page);
        await page.screenshot({ path: path.join(output, `${name}-${width}-teams.png`), fullPage: false });
        if (width < 960) {
          await page.locator('#team-form-message').scrollIntoViewIfNeeded();
          const end = await page.locator('#team-form').evaluate(e => e.getBoundingClientRect().bottom);
          const top = await page.locator('#admin-nav').evaluate(e => e.getBoundingClientRect().top);
          assert.ok(end <= top, 'bottom navigation must not cover the last form');
        }
        await page.locator('#admin-nav a[href="#competition-management"]').click();
        await page.screenshot({ path: path.join(output, `${name}-${width}-competitions.png`) });
        await page.locator('#admin-nav a[href="#schedule-management"]').click();
        await overflow(page);
        assert.equal(await page.locator('#scheduled-match-list li').last().getByRole('button', { name: 'Eliminar', exact: true }).isDisabled(), true);
        await page.locator('#scheduled-match-list li').last().getByRole('button', { name: 'Editar', exact: true }).click();
        assert.equal(await page.locator('#schedule-team1').isDisabled(), true);
        assert.equal(await page.locator('#schedule-team2').isDisabled(), true);
        await page.locator('#cancel-schedule-edit').click();
        await page.screenshot({ path: path.join(output, `${name}-${width}-schedule.png`) });
        await page.locator('#admin-nav a[href="#result-entry"]').click();
        await page.locator('#match-select').selectOption('2');
        assert.equal(await page.locator('.team1-points').first().inputValue(), '25');
        assert.equal(await page.locator('.team2-points').first().inputValue(), '10');
        await page.locator('#match-select').selectOption('1');
        await page.locator('#set-count').selectOption('5');
        assert.equal(await page.locator('.set-row').count(), 5);
        await page.locator('#set-count').selectOption('3');
        for (const input of await page.locator('.team1-points').all()) await input.fill('25');
        for (const input of await page.locator('.team2-points').all()) await input.fill('10');
        await overflow(page);
        await page.screenshot({ path: path.join(output, `${name}-${width}-result.png`) });
        await page.locator('#save-result').click();
        await page.waitForFunction(() => document.querySelector('#result-message').textContent.includes('guardado'));
        assert.ok(writes.some(r => r.method === 'PUT' && r.path === '/api/admin/matches/1/result' && r.csrf === 'qa-csrf'));
        assert.deepEqual(errors, []);
        console.log(`${name} ${width}: navigation, forms, dialogs, result submission and overflow passed`);
        await page.close();
      }
    } finally { await browser.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
