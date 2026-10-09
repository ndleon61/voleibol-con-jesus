const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function client(status = 200) {
  const calls = [];
  const redirects = [];
  const context = vm.createContext({
    URL,
    document: {querySelector: () => ({content: "csrf"})},
    window: {location: {origin: "http://localhost:3001", assign: url => redirects.push(url)}},
    fetch: async (url, options) => {calls.push({url, options}); return {status};},
  });
  const source = fs.readFileSync(path.join(__dirname, "../admin.js"), "utf8");
  vm.runInContext(source.slice(0, source.indexOf("const matchSelect")), context);
  return {context, calls, redirects};
}

test("selected tournament scopes existing dashboard requests", async () => {
  const {context, calls} = client();
  context.window.selectedTournamentId = 7;
  for (const endpoint of ["/api/teams", "/api/jornadas", "/api/standings", "/api/admin/stats", "/api/admin/jornadas/2/matches", "/api/admin/matches/3/result"]) {
    await context.adminFetch(endpoint + "?existing=yes");
    const url = new URL(calls.at(-1).url, "http://localhost");
    assert.equal(url.searchParams.get("tournament_id"), "7");
    assert.equal(url.searchParams.get("existing"), "yes");
    assert.equal(calls.at(-1).options.credentials, "same-origin");
  }
});

test("global catalog and explicit competition routes are not rewritten", async () => {
  const {context, calls} = client();
  context.window.selectedTournamentId = 7;
  for (const endpoint of ["/api/admin/teams", "/api/admin/teams/2", "/api/admin/seasons", "/api/admin/tournaments/2/teams", "/api/tournaments/2/standings"]) {
    await context.adminFetch(endpoint);
    assert.equal(calls.at(-1).url, endpoint);
  }
});

test("default public selection remains backward compatible", async () => {
  const {context, calls} = client();
  await context.adminFetch("/api/jornadas");
  assert.equal(calls[0].url, "/api/jornadas");
});

test("expired authentication still redirects to Spanish login", async () => {
  const {context, redirects} = client(401);
  await assert.rejects(context.adminFetch("/api/admin/tournaments"), /Tu sesión ha caducado/);
  assert.deepEqual(redirects, ["/login?motivo=sesion"]);
});
