const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const { Element } = require('./public-test-helpers.cjs');
const source = fs.readFileSync('admin.js', 'utf8');

test('admin navigation follows hash changes and focuses the selected section', () => {
  const links = ['#panel', '#team-management', '#competition-management', '#schedule-management', '#result-entry'].map(hash => {
    const link = new Element(); link.hash = hash; return link;
  });
  const nav = new Element(); nav.links = links;
  const targets = new Map(links.map(link => [link.hash.slice(1), new Element()]));
  const listeners = {};
  const window = { location: { hash: '' }, addEventListener: (name, fn) => { listeners[name] = fn; } };
  const document = { getElementById: id => id === 'admin-nav' ? nav : targets.get(id) };
  vm.runInNewContext(source.slice(source.indexOf('function initAdminNavigation()')), { window, document });
  assert.equal(links[0].getAttribute('aria-current'), 'location');
  window.location.hash = '#team-management'; listeners.hashchange();
  assert.equal(links[1].getAttribute('aria-current'), 'location');
  assert.equal(links.filter(link => link.classList.contains('active')).length, 1);
  nav.listeners.click({ target: { closest: () => links[1] } });
  assert.equal(targets.get('team-management').focused, true);
  window.location.hash = '#panel'; listeners.hashchange();
  assert.equal(links[1].getAttribute('aria-current'), undefined);
  assert.equal(links[0].getAttribute('aria-current'), 'location');
});

test('icon tools retain Spanish accessible names and contextual tooltips', () => {
  const ctx = vm.createContext({ document: { createElementNS: () => {
    const icon = new Element(); icon.append = () => {}; return icon;
  } } });
  vm.runInContext(source.slice(source.indexOf('function decorateAdminTool('), source.indexOf('let matches =')), ctx);
  for (const action of ['Editar', 'Eliminar']) {
    const button = new Element(); button.replaceChildren = icon => { button.icon = icon; };
    button.setAttribute('aria-label', `${action} La Furia Roja`);
    ctx.decorateAdminTool(button, action);
    assert.equal(button.getAttribute('aria-label'), `${action} La Furia Roja`);
    assert.equal(button.title, `${action} La Furia Roja`);
    assert.equal(button.icon.getAttribute('aria-hidden'), 'true');
    assert.equal(button.classList.contains('tool-button'), true);
    assert.equal(button.classList.contains('delete-tool'), action === 'Eliminar');
  }
});
