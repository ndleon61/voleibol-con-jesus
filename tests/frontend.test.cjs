const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const { Element, context, fixture } = require('./public-test-helpers.cjs');

test('set scores stop at the first winning point', () => {
  const { run } = context();
  for (const [a, b, valid] of [[25, 0, true], [26, 24, true], [27, 25, true], [26, 0, false], [27, 24, false], [25, -1, false], [25.5, 0, false]]) {
    assert.equal(run(`isValidSet({team1Points:${a},team2Points:${b}},1)`), valid);
  }
});

test('database text is escaped and finished games never appear in pending matches', () => {
  const { run, element } = context();
  const data = fixture();
  data.teams[0].name = '<img src=x onerror=alert(1)>';
  data.teams[0].logo = 'javascript:alert(1)';
  data.standings[0].team = data.teams[0].name;
  data.jornadas[0].number = '<script>bad</script>';
  data.jornadas[0].games[0].team1 = data.teams[0].name;
  run(`state.data=${JSON.stringify(data)}; renderApp();`);
  assert.match(element('standings').innerHTML, /&lt;img/);
  assert.doesNotMatch(element('teams').innerHTML, /<img src=x|javascript:/);
  assert.match(element('upcoming-matches').innerHTML, /&lt;script&gt;bad/);
  assert.doesNotMatch(element('upcoming-matches').innerHTML, /Finalizado/);
  assert.match(element('results').innerHTML, /3–0/);
});

test('invalid completed matches are not presented as zero-zero results', () => {
  const { run } = context();
  const html = run(`matchHTML({team1:'A',team2:'B',status:'finished',results:{sets:[{team1Points:25,team2Points:0}]}})`);
  assert.match(html, /Resultado pendiente de revisión/);
  assert.doesNotMatch(html, /0–0|final-score/);
});

test('calendar dates use Spanish Havana time regardless of browser time zone', () => {
  const { run } = context();
  assert.match(run(`matchSchedule({startsAt:'2026-07-16T00:00:00Z'})`), /15 jul.*20:00/);
  assert.equal(run(`matchSchedule({time:'17:30'})`), 'Fecha por confirmar · 17:30');
  assert.equal(run(`matchSchedule({startsAt:'invalid'})`), 'Fecha y horario por confirmar');
  assert.match(run(`competitionDate('2026-07-16')`), /16 jul/);
});

test('existing shared score validation fixtures still agree with the backend', () => {
  const shared = JSON.parse(fs.readFileSync('tests/business-rules.json', 'utf8'));
  const { run } = context();
  for (const item of shared.scores) {
    const sets = item.sets.map(([team1Points, team2Points], i) => ({ team1Points, team2Points, ...(item.numbers ? { setNumber: item.numbers[i] } : {}) }));
    assert.equal(run(`isValidMatch(${JSON.stringify({ sets })})`), item.valid, item.name);
  }
});

test('standings render API order and values without recalculating or inventing points', () => {
  const { run, element } = context();
  const data = fixture();
  data.standings.reverse();
  data.standings[0].wins = 17;
  run(`state.data=${JSON.stringify(data)}; renderStandings();`);
  const html = element('standings').innerHTML;
  assert.ok(html.indexOf('>B<') < html.indexOf('>A<'));
  assert.match(html, /<td>17<\/td>/);
  assert.equal(run(`typeof calculateStandings`), 'undefined');
});

test('missing, failed, unsafe and historical logos have safe identity-preserving fallbacks', () => {
  const { run, element } = context();
  assert.match(run(`logoHTML('Equipo largo', '')`), /Sin logotipo/);
  for (const url of ['https://evil.test/x.png', '//evil.test/x.png', '/media/../secret.png', 'data:image/png,evil']) {
    assert.doesNotMatch(run(`logoHTML('Equipo', ${JSON.stringify(url)})`), /<img/);
  }
  assert.equal(run(`safeLogo('/media/los_lobos.JPG')`), '/media/preview-los_lobos.webp');
  assert.equal(run(`state.selected={status:'archived'}; safeLogo('/team-logos/'+'a'.repeat(32)+'.webp')`), '/team-logos/' + 'a'.repeat(32) + '.webp');
  assert.equal(run(`safeLogo('/media/los_lobos.JPG')`), '/media/los_lobos.JPG');
  const image = new Element();
  element('teams').images = [image];
  run(`insertHTML(byId('teams'), 'test')`);
  image.listeners.error();
  assert.equal(image.removed, true);
});

test('empty tournaments have independent Spanish empty states', () => {
  const { run, element } = context();
  run(`state.data={teams:[],jornadas:[],standings:[]}; renderApp();`);
  assert.match(element('teams').innerHTML, /No hay equipos inscritos/);
  assert.match(element('results').innerHTML, /Todavía no hay resultados/);
  assert.match(element('upcoming-matches').innerHTML, /No hay partidos pendientes/);
  assert.match(element('standings').innerHTML, /No hay equipos/);
  assert.match(element('featured-match').innerHTML, /No hay próximos partidos/);
});

test('long team names and quote characters remain complete and escaped', () => {
  const { run } = context();
  const name = 'NombreMuyLargo'.repeat(7) + ' "<equipo>"';
  const html = run(`matchHTML({team1:${JSON.stringify(name)},team2:'B',status:'scheduled'})`);
  assert.match(html, /NombreMuyLargoNombreMuyLargo/);
  assert.match(html, /&quot;&lt;equipo&gt;&quot;/);
  assert.doesNotMatch(html, /<equipo>/);
});

test('featured match skips past schedules and unconfirmed dates without claiming live scoring', () => {
  const { run, element } = context();
  const data = fixture();
  data.jornadas[0].games.unshift({ id: 5, team1: 'Pasado', team2: 'B', status: 'live', startsAt: '2000-01-01T12:00:00Z' });
  run(`state.data=${JSON.stringify(data)}; renderMatches();`);
  assert.doesNotMatch(element('featured-match').innerHTML, /Pasado|En vivo/);
  assert.match(element('featured-match').innerHTML, /loading="eager"|>A</);
});

test('closed tournaments never advertise archived schedules as future encounters', () => {
  const { run, element } = context();
  run(`state.selected={status:'archived'}; state.data=${JSON.stringify(fixture())}; renderMatches();`);
  assert.match(element('featured-match').innerHTML, /competición cerrada/);
  assert.doesNotMatch(element('featured-match').innerHTML, /match-card/);
  assert.match(element('upcoming-matches').innerHTML, /Pendiente/);
});
