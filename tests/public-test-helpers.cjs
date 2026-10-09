const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor() {
    this.html = ''; this.attributes = {}; this.listeners = {}; this.images = []; this.hidden = false;
    const classes = new Set();
    this.classList = {
      add: value => classes.add(value), contains: value => classes.has(value),
      toggle(value, force) {
        const open = force === undefined ? !classes.has(value) : force;
        if (open) classes.add(value); else classes.delete(value);
        return open;
      },
    };
  }
  set textContent(value) { this.text = String(value); }
  get textContent() { return this.text || ''; }
  get innerHTML() { return this.html; }
  set innerHTML(value) { this.html = value; }
  querySelectorAll(selector) { return selector === 'a' ? (this.links || []) : this.images; }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name]; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  focus() { this.focused = true; }
  remove() { this.removed = true; }
}

function context(fetch = async () => { throw new Error('No mock response'); }) {
  const elements = new Map();
  const document = {
    body: new Element(), listeners: {}, title: '',
    getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); },
    addEventListener(name, listener) { this.listeners[name] = listener; },
  };
  const ctx = vm.createContext({ document, fetch, AbortController, setTimeout, clearTimeout, console });
  const source = fs.readFileSync('app.js', 'utf8').replace(/initPublicSite\(\);\s*$/, '');
  vm.runInContext(source, ctx);
  const run = code => vm.runInContext(code, ctx);
  return { ctx, document, run, element: id => document.getElementById(id) };
}

function fixture() {
  return {
    teams: [{ id: 1, name: 'A', logo: '' }, { id: 2, name: 'B', logo: '' }],
    jornadas: [{ number: 1, games: [
      { id: 1, team1Id: 1, team2Id: 2, team1: 'A', team2: 'B', status: 'scheduled', startsAt: '2099-07-16T00:00:00Z' },
      { id: 2, team1Id: 1, team2Id: 2, team1: 'A', team2: 'B', status: 'finished', results: { sets: Array.from({ length: 3 }, (_, i) => ({ setNumber: i + 1, team1Points: 25, team2Points: 0 })) } },
    ] }],
    standings: [{ teamId: 1, team: 'A', wins: 1, losses: 0, setsWon: 3, setsLost: 0 }, { teamId: 2, team: 'B', wins: 0, losses: 1, setsWon: 0, setsLost: 3 }],
  };
}

module.exports = { Element, context, fixture };
