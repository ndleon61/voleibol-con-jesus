const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

class Element {
  constructor() {
    this.children = [];
    this.classList = { add() {}, toggle() {}, contains() { return false; } };
  }
  set textContent(value) {
    this.html = String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  }
  get innerHTML() { return this.html || ''; }
  set innerHTML(value) { this.html = value; if (!value) this.children = []; }
  appendChild(child) { this.children.push(child); }
  querySelector() { return new Element(); }
  setAttribute() {}
  addEventListener() {}
}

function context() {
  const elements = Object.fromEntries(['teams', 'standings', 'results', 'upcoming-matches'].map(id => [id, new Element()]));
  const ctx = vm.createContext({ console, document: {
    createElement: () => new Element(), getElementById: id => elements[id],
  } });
  const source = fs.readFileSync('app.js', 'utf8').replace(/loadTeams\(\);\s*$/, '');
  vm.runInContext(source, ctx);
  return { ctx, elements };
}

test('set scores stop at the first winning point', () => {
  const { ctx } = context();
  for (const [a, b, valid] of [[25, 0, true], [26, 24, true], [27, 25, true], [26, 0, false], [27, 24, false], [25, -1, false], [25.5, 0, false]]) {
    assert.equal(vm.runInContext(`isValidSet({team1Points:${a},team2Points:${b}},1)`, ctx), valid);
  }
});

test('database text is escaped and finished games are excluded from upcoming matches', () => {
  const { ctx, elements } = context();
  vm.runInContext(`
    teams = [{name: '<img src=x onerror=alert(1)>', logo: ''}, {name: 'B', logo: ''}];
    jornadas = [{number: '<script>bad</script>', games: [
      {team1: teams[0].name, team2: 'B', time: '<b>10</b>', status: 'scheduled'},
      {team1: teams[0].name, team2: 'B', status: 'finished', results: {sets: Array.from({length:3}, () => ({team1Points:25,team2Points:0}))}}
    ]}]; renderApp();
  `, ctx);
  assert.match(elements.standings.children[0].innerHTML, /&lt;img/);
  assert.doesNotMatch(elements.teams.children[0].innerHTML, /<img src=x/);
  assert.equal(elements['upcoming-matches'].children[0].children.length, 1);
  assert.match(elements['upcoming-matches'].children[0].children[0].innerHTML, /&lt;b&gt;10/);
});

test('invalid completed matches do not affect standings', () => {
  const { ctx } = context();
  assert.equal(vm.runInContext(`teams=[{name:'A'},{name:'B'}]; jornadas=[{games:[{team1:'A',team2:'B',status:'finished',results:{sets:[{team1Points:25,team2Points:0}]}}]}]; calculateStandings().A.wins`, ctx), 0);
});

test('calendar dates use Spanish Havana time regardless of browser time zone', () => {
  const { ctx, elements } = context();
  const text = vm.runInContext(`matchSchedule({startsAt:'2026-07-16T00:00:00+00:00'})`, ctx);
  assert.match(text, /15/);
  assert.match(text, /jul/);
  assert.match(text, /20:00/);
  vm.runInContext(`teams=[{name:'A',logo:''},{name:'B',logo:''}]; jornadas=[{number:1,games:[{id:3,team1:'A',team2:'B',startsAt:'2026-07-16T00:00:00Z',status:'scheduled'},{id:4,team1:'A',team2:'B',startsAt:'2026-07-16T01:00:00Z',status:'finished',results:{sets:Array.from({length:3},()=>({team1Points:25,team2Points:0}))}}]}]; renderApp();`, ctx);
  assert.equal(elements['upcoming-matches'].children[0].children.length, 1);
  assert.match(elements['upcoming-matches'].children[0].children[0].innerHTML, /20:00/);
  assert.ok(elements.results.children.length > 0);
  assert.match(elements.results.children[0].innerHTML, /21:00/);
});

test('scoring and rankings agree with shared backend fixtures', () => {
  const fixture = JSON.parse(fs.readFileSync('tests/business-rules.json','utf8'));
  const {ctx,elements} = context();
  for (const item of fixture.scores) {
    const sets=item.sets.map(([team1Points,team2Points],i)=>({team1Points,team2Points,...(item.numbers?{setNumber:item.numbers[i]}:{})}));
    assert.equal(vm.runInContext(`isValidMatch(${JSON.stringify({sets})})`,ctx),item.valid,item.name);
  }
  const games=fixture.matches.map(m=>({id:m.id,team1:fixture.teams.find(t=>t.id===m.team1).name,team2:fixture.teams.find(t=>t.id===m.team2).name,status:m.status,results:{sets:m.sets.map(([team1Points,team2Points],i)=>({team1Points,team2Points,setNumber:i+1}))}}));
  vm.runInContext(`teams=${JSON.stringify(fixture.teams)}; jornadas=[{number:1,games:${JSON.stringify(games)}}]; renderApp();`,ctx);
  const table=JSON.parse(vm.runInContext('JSON.stringify(calculateStandings())',ctx));
  for (const t of fixture.standings) assert.deepEqual(table[t.team],{name:t.team,wins:t.wins,losses:t.losses,setsFor:t.setsWon,setsAgainst:t.setsLost});
  for(const [i,t] of fixture.standings.entries()) assert.match(elements.standings.children[i].innerHTML,new RegExp(`<td>${t.team}</td>`));
});
