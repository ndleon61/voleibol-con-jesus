const byId = id => document.getElementById(id);
const state = {
  seasons: [], tournaments: [], selected: null, data: null, catalogReady: false,
  request: 0, controller: null, cache: new Map(), pendingLimit: 4, resultLimit: 3,
};
const competitionLabels = { planned: "Planificado", active: "En curso", completed: "Completado", archived: "Archivado" };
const legacyPreviews = {
  "/media/los_abusadores.JPG": "/media/preview-los_abusadores.webp",
  "/media/los_lobos.JPG": "/media/preview-los_lobos.webp",
  "/media/polea.JPG": "/media/preview-polea.webp",
  "/media/la_furia_roja.JPG": "/media/preview-la_furia_roja.webp",
  "/media/la_ofensiva_aplastante.JPG": "/media/preview-la_ofensiva_aplastante.webp",
};

function escapeHTML(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function matchSchedule(game) {
  const date = game.startsAt ? new Date(game.startsAt) : null;
  if (!date || Number.isNaN(date.getTime())) {
    return game.time && game.time !== "Horario por confirmar" ? `Fecha por confirmar · ${game.time}` : "Fecha y horario por confirmar";
  }
  return new Intl.DateTimeFormat("es-CU", {
    timeZone: "America/Havana", dateStyle: "medium", timeStyle: "short", hourCycle: "h23",
  }).format(date);
}

function competitionDate(value) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return "";
  const date = new Date(`${value}T12:00:00Z`);
  return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat("es-CU", {
    timeZone: "America/Havana", dateStyle: "medium",
  }).format(date);
}

// Retain the existing validation for score presentation; ranking comes only from the API.
function isValidSet(set, number, bestOf = 5) {
  if (!set || !Number.isSafeInteger(set.team1Points) || !Number.isSafeInteger(set.team2Points) ||
      set.team1Points < 0 || set.team2Points < 0 || set.team1Points > 2147483647 || set.team2Points > 2147483647) return false;
  const winner = Math.max(set.team1Points, set.team2Points);
  const loser = Math.min(set.team1Points, set.team2Points);
  const target = bestOf === 5 && number === 5 ? 15 : 25;
  return winner >= target && winner - loser >= 2 && (winner === target || winner - loser === 2);
}

function isValidMatch(results) {
  const bestOf = results?.bestOf ?? 5;
  const needed = Math.floor(bestOf / 2) + 1;
  if (![3, 5].includes(bestOf) || !results || !Array.isArray(results.sets) || results.sets.length < needed || results.sets.length > bestOf) return false;
  let wins1 = 0, wins2 = 0;
  for (const [index, set] of results.sets.entries()) {
    if (!isValidSet(set, index + 1, bestOf) || (set.setNumber !== undefined && set.setNumber !== index + 1)) return false;
    if (set.team1Points > set.team2Points) wins1++; else wins2++;
    if (wins1 === needed || wins2 === needed) return index === results.sets.length - 1;
  }
  return false;
}

function calculateSets(results) {
  if (!isValidMatch(results)) return null;
  const team1Sets = results.sets.filter(set => set.team1Points > set.team2Points).length;
  return { team1Sets, team2Sets: results.sets.length - team1Sets };
}

function safeLogo(url) {
  if (typeof url !== "string" || !/^\/(?:media\/[a-zA-Z0-9_-]+\.(?:JPG|jpg|jpeg|png|webp)|team-logos\/[a-f0-9]{32}\.webp)$/.test(url)) return "";
  const closed = ["completed", "archived"].includes(state.selected?.status);
  return closed ? url : (legacyPreviews[url] || url);
}

function logoHTML(name, url, eager = false) {
  const initials = String(name || "Equipo").trim().split(/\s+/).slice(0, 2).map(word => [...word][0] || "").join("").toUpperCase();
  const logo = safeLogo(url);
  return `<span class="logo-shell"><span class="logo-fallback" aria-hidden="true">${escapeHTML(initials)}</span>${logo ? `<img src="${escapeHTML(logo)}" alt="Logotipo de ${escapeHTML(name)}" width="64" height="64" loading="${eager ? "eager" : "lazy"}" decoding="async">` : '<span class="sr-only">Sin logotipo</span>'}</span>`;
}

function insertHTML(element, html) {
  element.innerHTML = html;
  element.querySelectorAll("img").forEach(img => img.addEventListener("error", () => {
    img.remove();
  }, { once: true }));
}

function matchHTML(game, eager = false) {
  const completed = game.status === "finished";
  const score = completed ? calculateSets(game.results) : null;
  const label = completed ? "Finalizado" : "Pendiente";
  const center = score ? `${score.team1Sets}–${score.team2Sets}` : "VS";
  const scoreLabel = score ? `${game.team1}: ${score.team1Sets} sets; ${game.team2}: ${score.team2Sets} sets.` : `${game.team1} contra ${game.team2}.`;
  return `<article class="match-card">
    <div class="match-meta"><span>Jornada ${escapeHTML(game.jornadaNumber)}</span><span class="match-status ${completed ? "finished" : "scheduled"}">${label}</span></div>
    <div class="match-teams">
      <div class="match-team">${logoHTML(game.team1, game.team1Logo, eager)}<h3 class="team-name">${escapeHTML(game.team1)}</h3></div>
      <p class="match-center ${score ? "final-score" : ""}" aria-label="${escapeHTML(scoreLabel)}">${center}</p>
      <div class="match-team">${logoHTML(game.team2, game.team2Logo, eager)}<h3 class="team-name">${escapeHTML(game.team2)}</h3></div>
    </div><p class="match-date">${escapeHTML(matchSchedule(game))}</p>
    ${completed && !score ? '<p class="match-date">Resultado pendiente de revisión.</p>' : ""}
    ${score ? `<details class="set-details"><summary>Ver sets del partido</summary><div class="set-scores">${game.results.sets.map((set, i) => `<p class="set-score"><span>Set ${i + 1}</span>${set.team1Points}–${set.team2Points}</p>`).join("")}</div></details>` : ""}
  </article>`;
}

function flattenedMatches(data) {
  return data.jornadas.flatMap(jornada => jornada.games.map(game => ({ ...game, jornadaNumber: jornada.number })));
}

function matchTimestamp(game) {
  const stamp = game.startsAt ? Date.parse(game.startsAt) : NaN;
  return Number.isNaN(stamp) ? Infinity : stamp;
}

function renderMatches() {
  const games = flattenedMatches(state.data);
  const pending = games.filter(game => game.status !== "finished").sort((a, b) => matchTimestamp(a) - matchTimestamp(b) || a.jornadaNumber - b.jornadaNumber || a.id - b.id);
  const completed = games.filter(game => game.status === "finished").sort((a, b) => {
    const left = matchTimestamp(a), right = matchTimestamp(b);
    return (Number.isFinite(left) && Number.isFinite(right) ? right - left : 0) || b.jornadaNumber - a.jornadaNumber || b.id - a.id;
  });
  const closed = ["completed", "archived"].includes(state.selected?.status);
  const future = closed ? null : pending.find(game => Number.isFinite(matchTimestamp(game)) && matchTimestamp(game) >= Date.now());
  insertHTML(byId("featured-match"), future ? matchHTML(future, true) : `<p class="featured-empty">${closed ? "No hay próximos partidos en esta competición cerrada." : "No hay próximos partidos con fecha confirmada."}</p>`);
  insertHTML(byId("upcoming-matches"), pending.length ? pending.slice(0, state.pendingLimit).map(game => matchHTML(game)).join("") : '<p class="empty-state">No hay partidos pendientes en este torneo.</p>');
  insertHTML(byId("results"), completed.length ? completed.slice(0, state.resultLimit).map(game => matchHTML(game)).join("") : '<p class="empty-state">Todavía no hay resultados en este torneo.</p>');
  byId("match-count").textContent = `${pending.length} partidos`;
  byId("result-count").textContent = `${completed.length} partidos`;
  byId("more-matches").hidden = pending.length <= state.pendingLimit;
  byId("more-results").hidden = completed.length <= state.resultLimit;
}

function renderStandings() {
  // Preserve server order and values, including historical identities. Never recompute standings.
  insertHTML(byId("standings"), state.data.standings.length ? state.data.standings.map((team, index) =>
    `<tr class="${index === 0 ? "leader" : ""}"><td class="standing-rank">${index + 1}</td><th scope="row"><span class="standing-team">${logoHTML(team.team, team.logo)}<span>${escapeHTML(team.team)}</span></span></th><td>${escapeHTML(team.wins)}</td><td class="stat-detail">${escapeHTML(team.losses)}</td><td class="stat-detail">${escapeHTML(team.setsWon)}</td><td class="stat-detail">${escapeHTML(team.setsLost)}</td></tr>`
  ).join("") : '<tr><td colspan="6" class="empty-state">No hay equipos en la clasificación.</td></tr>');
}

function renderTeams() {
  const games = flattenedMatches(state.data);
  const standings = new Map(state.data.standings.map((team, index) => [team.teamId, { ...team, position: index + 1 }]));
  insertHTML(byId("teams"), state.data.teams.length ? state.data.teams.map(team => {
    const standing = standings.get(team.id);
    const fixtures = games.filter(game => game.team1Id === team.id || game.team2Id === team.id);
    return `<article class="team-card">${logoHTML(team.name, team.logo)}<div><h3>${escapeHTML(team.name)}</h3><p>Participante del torneo</p>
      ${standing ? `<p>Posición ${standing.position} · ${escapeHTML(standing.wins)} ${standing.wins === 1 ? "victoria" : "victorias"} · ${escapeHTML(standing.losses)} ${standing.losses === 1 ? "derrota" : "derrotas"}</p>` : ""}
      <details class="team-fixtures"><summary>Partidos del equipo (${fixtures.length})</summary>${fixtures.length ? `<ul>${fixtures.map(game => {
        const score = game.status === "finished" ? calculateSets(game.results) : null;
        return `<li>${escapeHTML(game.team1)} contra ${escapeHTML(game.team2)}<br>${escapeHTML(matchSchedule(game))}<br>${score ? `Finalizado · ${score.team1Sets}–${score.team2Sets}` : game.status === "finished" ? "Resultado pendiente de revisión" : "Pendiente"}</li>`;
      }).join("")}</ul>` : '<p>No hay partidos registrados.</p>'}</details></div></article>`;
  }).join("") : '<p class="empty-state">No hay equipos inscritos en este torneo.</p>');
  byId("team-count").textContent = `${state.data.teams.length} equipos`;
}

function renderApp() {
  renderMatches(); renderStandings(); renderTeams();
  byId("league-content").hidden = false;
  byId("league-content").setAttribute("aria-busy", "false");
}

function renderCompetition() {
  const tournament = state.selected;
  const season = state.seasons.find(item => item.id === tournament?.seasonId);
  byId("season-context").textContent = tournament && !tournament.isPublic ? "Historial de temporadas" : "Temporada actual";
  byId("season-name").textContent = season?.name || "Liga de voleibol";
  byId("tournament-name").textContent = tournament?.name || "Voli Conociendo a Jesús";
  byId("tournament-status").textContent = tournament ? competitionLabels[tournament.status] || "Torneo" : "Sin torneo activo";
  const start = competitionDate(tournament?.startDate), end = competitionDate(tournament?.endDate);
  byId("tournament-dates").textContent = start && end ? `${start} — ${end}` : start ? `Desde ${start}` : end ? `Hasta ${end}` : "";
  document.title = tournament ? `${tournament.name} | Voli Conociendo a Jesús` : "Voli Conociendo a Jesús | Liga de voleibol";
}

function renderHistory(seasonId = state.selected?.seasonId) {
  const seasonSelect = byId("season-select"), tournamentSelect = byId("tournament-select");
  seasonSelect.innerHTML = '<option value="">Todas las temporadas</option>' + state.seasons.map(season => `<option value="${season.id}">${escapeHTML(season.name)}</option>`).join("");
  seasonSelect.value = seasonId ? String(seasonId) : "";
  const tournaments = state.tournaments.filter(item => !seasonId || item.seasonId === Number(seasonId));
  tournamentSelect.innerHTML = '<option value="">Seleccionar torneo</option>' + tournaments.map(item => `<option value="${item.id}">${escapeHTML(item.name)} · ${competitionLabels[item.status] || "Torneo"}</option>`).join("");
  tournamentSelect.value = tournaments.some(item => item.id === state.selected?.id) ? String(state.selected.id) : "";
  seasonSelect.disabled = false;
  tournamentSelect.disabled = !tournaments.length;
  byId("current-tournament").disabled = !state.tournaments.some(item => item.isPublic);
  insertHTML(byId("history-list"), tournaments.length ? [...tournaments].reverse().map(item => `<article class="history-item"><div><h3>${escapeHTML(item.name)}</h3><p>${escapeHTML(state.seasons.find(season => season.id === item.seasonId)?.name || "Temporada")} · ${competitionLabels[item.status] || "Torneo"}${item.isPublic ? " · Torneo actual" : ""}</p></div><button type="button" data-tournament="${item.id}" aria-pressed="${item.id === state.selected?.id}" aria-label="Ver ${escapeHTML(item.name)}">${item.id === state.selected?.id ? "Seleccionado" : "Ver torneo"}</button></article>`).join("") : '<p class="empty-state">No hay torneos en esta temporada.</p>');
  byId("history-status").textContent = ["completed", "archived"].includes(state.selected?.status) ? "Torneo cerrado: se muestran los nombres y logotipos históricos." : state.selected ? `Mostrando ${state.selected.name}.` : "No hay un torneo público activo. Puedes consultar otros torneos.";
}

async function fetchJSON(url, signal) {
  const response = await fetch(url, { signal, cache: "no-store", credentials: "omit", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error("No se pudieron consultar los datos.");
  const data = await response.json();
  if (!Array.isArray(data)) throw new Error("La respuesta no está disponible.");
  return data;
}

async function catalog(url, signal) {
  const rows = [];
  for (let offset = 0; ; offset += 500) {
    const page = await fetchJSON(`${url}?limit=500&offset=${offset}`, signal);
    rows.push(...page);
    if (page.length < 500) return rows;
    if (offset >= 1000000) throw new Error("El catálogo no está disponible.");
  }
}

function consultedAt(timestamp, fromCache) {
  const time = new Intl.DateTimeFormat("es-CU", { timeZone: "America/Havana", dateStyle: "short", timeStyle: "short", hourCycle: "h23" }).format(timestamp);
  byId("data-status").textContent = `${fromCache ? "Consulta anterior de esta visita" : "Datos consultados"} · ${time} (Cuba)`;
}

function showLoading() {
  byId("league-content").hidden = false;
  byId("league-content").setAttribute("aria-busy", "true");
  insertHTML(byId("featured-match"), '<p class="featured-empty">Cargando el próximo partido…</p>');
  insertHTML(byId("upcoming-matches"), '<p class="empty-state loading-placeholder">Cargando partidos…</p>');
  insertHTML(byId("results"), '<p class="empty-state loading-placeholder">Cargando resultados…</p>');
  insertHTML(byId("teams"), '<p class="empty-state">Cargando equipos…</p>');
  insertHTML(byId("standings"), '<tr><td colspan="6">Cargando clasificación…</td></tr>');
  ["match-count", "result-count", "team-count"].forEach(id => { byId(id).textContent = ""; });
  ["more-matches", "more-results"].forEach(id => { byId(id).hidden = true; });
}

async function loadLeague({ tournamentId = state.selected?.id, refresh = false } = {}) {
  const requestId = ++state.request;
  state.controller?.abort();
  const controller = new AbortController();
  state.controller = controller;
  const timeout = setTimeout(() => controller.abort(), 45000);
  byId("error-notice").hidden = true;
  byId("refresh-data").disabled = true;
  showLoading();
  byId("data-status").textContent = "Cargando los datos del torneo…";
  try {
    if (!state.catalogReady || refresh) {
      const [seasons, tournaments] = await Promise.all([catalog("/api/seasons", controller.signal), catalog("/api/tournaments", controller.signal)]);
      if (requestId !== state.request) return;
      const validIdentity = item => item && Number.isSafeInteger(item.id) && item.id > 0 && typeof item.name === "string";
      if (!seasons.every(validIdentity) || !tournaments.every(item => validIdentity(item) && Number.isSafeInteger(item.seasonId) &&
          typeof item.isPublic === "boolean" && Object.prototype.hasOwnProperty.call(competitionLabels, item.status))) throw new Error("Catálogo no disponible.");
      state.seasons = seasons; state.tournaments = tournaments; state.catalogReady = true;
      if (refresh) state.cache.clear();
    }
    state.selected = state.tournaments.find(item => item.id === Number(tournamentId)) ||
      (!tournamentId ? state.tournaments.find(item => item.isPublic) : null) || null;
    renderCompetition(); renderHistory();
    state.pendingLimit = 4; state.resultLimit = 3;
    const selectedId = state.selected?.id;
    const cached = state.cache.get(selectedId);
    const closed = ["completed", "archived"].includes(state.selected?.status);
    if (cached && (closed || Date.now() - cached.timestamp < 60000)) {
      state.data = cached.data; renderApp(); consultedAt(cached.timestamp, true); return;
    }
    if (!selectedId) {
      state.data = { teams: [], jornadas: [], standings: [] }; renderApp();
      byId("data-status").textContent = "No hay un torneo público activo. Consulta el historial.";
      return;
    }
    const base = `/api/tournaments/${selectedId}`;
    const [teams, jornadas, standings] = await Promise.all(["teams", "jornadas", "standings"].map(endpoint => fetchJSON(`${base}/${endpoint}`, controller.signal)));
    if (requestId !== state.request) return;
    if (!teams.every(team => Number.isSafeInteger(team.id) && typeof team.name === "string") ||
        !jornadas.every(jornada => Array.isArray(jornada.games)) || !standings.every(team => typeof team.team === "string")) throw new Error("Datos no disponibles.");
    state.data = { teams, jornadas, standings };
    const timestamp = Date.now();
    state.cache.set(selectedId, { data: state.data, timestamp });
    if (state.cache.size > 5) state.cache.delete(state.cache.keys().next().value);
    renderApp(); consultedAt(timestamp, false);
  } catch (error) {
    if (requestId !== state.request) return;
    byId("league-content").hidden = true;
    byId("error-notice").hidden = false;
    byId("error-message").textContent = "No se pudieron cargar los datos. Comprueba tu conexión e inténtalo de nuevo.";
    byId("data-status").textContent = "Los datos no están disponibles.";
    byId("history-status").textContent = "No se pudo completar la consulta. Pulsa Reintentar.";
    insertHTML(byId("featured-match"), '<p class="featured-empty">El próximo partido no está disponible.</p>');
  } finally {
    clearTimeout(timeout);
    if (requestId === state.request) {
      byId("refresh-data").disabled = false;
      byId("league-content").setAttribute("aria-busy", "false");
    }
  }
}

function setBottomTab(hash) {
  byId("bottom-nav").querySelectorAll("a").forEach(link => {
    if (link.hash === hash) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  });
}

function initPublicSite() {
  byId("main-nav").addEventListener("click", event => {
    const link = event.target.closest("a");
    if (link) { setBottomTab(link.hash); byId(link.hash.slice(1))?.focus({ preventScroll: true }); }
  });
  byId("bottom-nav").addEventListener("click", event => {
    const link = event.target.closest("a");
    if (link) { setBottomTab(link.hash); byId(link.hash.slice(1))?.focus({ preventScroll: true }); }
  });
  if (typeof window !== "undefined") {
    setBottomTab(window.location.hash || "#inicio");
    window.addEventListener("hashchange", () => setBottomTab(window.location.hash || "#inicio"));
  }
  byId("standings-details").addEventListener("click", () => {
    const open = byId("clasificacion").classList.toggle("show-statistics");
    byId("standings-details").setAttribute("aria-expanded", String(open));
    byId("standings-details").textContent = open ? "Ocultar estadísticas" : "Ver estadísticas";
  });
  byId("season-select").addEventListener("change", event => renderHistory(event.target.value));
  byId("tournament-select").addEventListener("change", event => {
    if (event.target.value) loadLeague({ tournamentId: Number(event.target.value) });
  });
  byId("history-list").addEventListener("click", event => {
    const button = event.target.closest("button[data-tournament]");
    if (button) loadLeague({ tournamentId: Number(button.dataset.tournament) });
  });
  byId("current-tournament").addEventListener("click", () => loadLeague({ tournamentId: state.tournaments.find(item => item.isPublic)?.id }));
  ["refresh-data", "retry-data"].forEach(id => byId(id).addEventListener("click", () => loadLeague({ refresh: true })));
  byId("more-matches").addEventListener("click", () => { state.pendingLimit += 12; renderMatches(); });
  byId("more-results").addEventListener("click", () => { state.resultLimit += 12; renderMatches(); });
  loadLeague();
}

initPublicSite();
