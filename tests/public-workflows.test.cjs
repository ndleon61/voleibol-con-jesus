const assert = require('node:assert/strict');
const test = require('node:test');
const { context, fixture } = require('./public-test-helpers.cjs');

const seasons = [{ id: 1, name: 'Temporada actual' }, { id: 2, name: 'Temporada anterior' }];
const tournaments = [{ id: 1, name: 'Actual', status: 'active', isPublic: true, seasonId: 1 }, { id: 2, name: 'Anterior', status: 'archived', isPublic: false, seasonId: 2 }];

function responses(calls, override) {
  return async (url, options) => {
    calls.push({ url, options });
    const value = override ? await override(url) : undefined;
    if (value !== undefined) return { ok: true, json: async () => value };
    const data = url.startsWith('/api/seasons') ? seasons : url.startsWith('/api/tournaments?') ? tournaments : fixture()[url.split('/').at(-1)];
    return { ok: true, json: async () => data };
  };
}

test('active tournament loads by default with five public GETs and no credentials', async () => {
  const calls = [], { run, element } = context(responses(calls));
  await run('loadLeague()');
  assert.equal(calls.length, 5);
  assert.equal(element('tournament-name').textContent, 'Actual');
  assert.ok(calls.every(call => call.options.credentials === 'omit' && call.options.cache === 'no-store'));
  assert.ok(calls.every(call => !call.url.includes('/admin/')));
});

test('historical selection scopes all views and retains snapshot names and logos', async () => {
  const calls = [];
  const historical = fixture();
  historical.teams[0].name = 'Nombre histórico';
  historical.teams[0].logo = '/team-logos/' + 'a'.repeat(32) + '.webp';
  historical.standings[0].team = 'Nombre histórico';
  historical.standings[0].logo = historical.teams[0].logo;
  historical.jornadas[0].games[0].team1 = 'Nombre histórico';
  historical.jornadas[0].games[0].team1Logo = historical.teams[0].logo;
  const { run, element } = context(responses(calls, url => url.startsWith('/api/tournaments/2/') ? historical[url.split('/').at(-1)] : undefined));
  await run('loadLeague()');
  await run('loadLeague({tournamentId:2})');
  assert.deepEqual(calls.slice(-3).map(call => call.url), ['/api/tournaments/2/teams', '/api/tournaments/2/jornadas', '/api/tournaments/2/standings']);
  for (const id of ['teams', 'standings', 'upcoming-matches']) assert.match(element(id).innerHTML, /Nombre histórico/);
  assert.match(element('history-status').textContent, /históricos/);
  assert.match(element('teams').innerHTML, /aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp/);
  assert.equal(element('season-name').textContent, 'Temporada anterior');
  assert.equal(element('season-context').textContent, 'Historial de temporadas');
});

test('recent data is reused with an explicit previous-query label and refresh bypasses it', async () => {
  const calls = [], { run, element } = context(responses(calls));
  await run('loadLeague()');
  await run('loadLeague({tournamentId:2})');
  await run('loadLeague({tournamentId:1})');
  assert.equal(calls.length, 8);
  assert.match(element('data-status').textContent, /Consulta anterior/);
  await run('loadLeague({refresh:true})');
  assert.equal(calls.length, 13);
});

test('network or API failures hide old results and retry really reloads data', async () => {
  let fail = true;
  const calls = [], { run, element } = context(async (url, options) => {
    if (fail) throw new Error('Private stack trace');
    return responses(calls)(url, options);
  });
  await run('loadLeague()');
  assert.equal(element('error-notice').hidden, false);
  assert.equal(element('league-content').hidden, true);
  assert.doesNotMatch(element('error-message').textContent, /Private|stack/);
  fail = false;
  await run('loadLeague({refresh:true})');
  assert.equal(element('error-notice').hidden, true);
  assert.equal(element('league-content').hidden, false);
});

test('unavailable and malformed responses produce a recoverable Spanish error', async () => {
  for (const response of [{ ok: false, status: 503 }, { ok: true, json: async () => ({ internal: 'error' }) }]) {
    const { run, element } = context(async () => response);
    await run('loadLeague()');
    assert.match(element('error-message').textContent, /No se pudieron cargar/);
    assert.equal(element('refresh-data').disabled, false);
  }
});

test('without an active tournament visitors can still browse history without fabricating a selection', async () => {
  const calls = [], { run, element } = context(responses(calls, url => url.startsWith('/api/tournaments?') ? tournaments.map(item => ({ ...item, isPublic: false })) : undefined));
  await run('loadLeague()');
  assert.equal(calls.length, 2);
  assert.match(element('data-status').textContent, /No hay un torneo público activo/);
  assert.match(element('history-list').innerHTML, /Anterior/);
  await run('loadLeague({tournamentId:2})');
  assert.equal(element('tournament-name').textContent, 'Anterior');
});

test('season filter and expanded statistics remain accessible', async () => {
  const { run, element } = context(responses([]));
  run('initPublicSite()');
  await new Promise(resolve => setTimeout(resolve, 0));
  element('season-select').listeners.change({ target: { value: '2' } });
  assert.match(element('history-list').innerHTML, /Anterior/);
  assert.doesNotMatch(element('history-list').innerHTML, /Actual/);
  element('standings-details').listeners.click();
  assert.equal(element('standings-details').getAttribute('aria-expanded'), 'true');
});

test('late responses from a previous tournament cannot overwrite a newer selection', async () => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const { run, element } = context(responses([], async url => {
    if (url.startsWith('/api/tournaments/1/')) { await gate; return fixture()[url.split('/').at(-1)]; }
    return undefined;
  }));
  const first = run('loadLeague()');
  await new Promise(resolve => setTimeout(resolve, 0));
  await run('loadLeague({tournamentId:2})');
  release(); await first;
  assert.equal(element('tournament-name').textContent, 'Anterior');
  assert.equal(run('state.selected.id'), 2);
});

test('catalog pagination does not silently omit previous seasons or tournaments', async () => {
  const calls = [], { run } = context(async url => {
    calls.push(url);
    return { ok: true, json: async () => url.includes('offset=0') ? Array.from({ length: 500 }, (_, id) => ({ id })) : [{ id: 501 }] };
  });
  const result = await run(`catalog('/api/tournaments')`);
  assert.equal(result.length, 501);
  assert.deepEqual(calls, ['/api/tournaments?limit=500&offset=0', '/api/tournaments?limit=500&offset=500']);
});

test('malformed catalog identities cannot inject markup into selectors', async () => {
  const { run, element } = context(responses([], url => url.startsWith('/api/seasons') ? [{ id: '1"><img src=x>', name: 'Temporada' }] : undefined));
  await run('loadLeague()');
  assert.equal(element('error-notice').hidden, false);
  assert.doesNotMatch(element('season-select').innerHTML, /<img/);
});

test('loading clears previous results immediately while keeping placeholder geometry', async () => {
  const { run, element } = context();
  run(`state.data=${JSON.stringify(fixture())}; renderApp(); showLoading();`);
  assert.match(element('upcoming-matches').innerHTML, /loading-placeholder/);
  assert.doesNotMatch(element('results').innerHTML, /3–0/);
  assert.equal(element('league-content').hidden, false);
  assert.equal(element('league-content').getAttribute('aria-busy'), 'true');
});

test('bottom navigation selects one accessible tab and focuses its destination', async () => {
  const { Element } = require('./public-test-helpers.cjs');
  const { run, element } = context(responses([]));
  const links = ['#inicio', '#partidos', '#clasificacion', '#equipos'].map(hash => {
    const link = new Element(); link.hash = hash; return link;
  });
  element('bottom-nav').links = links;
  run('initPublicSite()');
  await new Promise(resolve => setTimeout(resolve, 0));
  element('bottom-nav').listeners.click({ target: { closest: () => links[2] } });
  assert.equal(links[2].getAttribute('aria-current'), 'location');
  assert.equal(links.filter(link => link.getAttribute('aria-current') === 'location').length, 1);
  assert.equal(element('clasificacion').focused, true);
});
