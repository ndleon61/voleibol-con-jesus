(() => {
  const el = id => document.getElementById(id);
  const jornadaForm = el("jornada-form");
  const matchForm = el("schedule-form");
  const dialog = el("schedule-delete-dialog");
  let jornadas = [];
  let selected = "";
  let busy = false;
  let pendingDelete = null;
  let loadedTournament = null;
  const dateFormat = new Intl.DateTimeFormat("es-CU", { timeZone: "America/Havana", dateStyle: "medium", timeStyle: "short", hourCycle: "h23" });

  function message(id, text, error = false) {
    el(id).textContent = text;
    el(id).className = error ? "message-error" : "message-success";
  }
  function locked(match) { return match.status === "finished" || match.hasResults; }
  function setBusy(value) {
    busy = value;
    for (const control of document.querySelectorAll("#schedule-management input, #schedule-management select, #schedule-management button, #schedule-delete-dialog button")) {
      control.disabled = value;
    }
    matchForm.setAttribute("aria-busy", String(value));
    jornadaForm.setAttribute("aria-busy", String(value));
    if (!value) applyMatchLocks();
  }
  function currentMatch() {
    return jornadas.flatMap(j => j.games).find(m => String(m.id) === el("schedule-match-id").value);
  }
  function applyMatchLocks() {
    const match = currentMatch();
    el("schedule-jornada").disabled = busy || Boolean(match);
    el("schedule-team1").disabled = busy || Boolean(match && locked(match));
    el("schedule-team2").disabled = busy || Boolean(match && locked(match));
  }
  function resetJornada() {
    jornadaForm.reset();
    el("jornada-edit-id").value = "";
    el("jornada-form-title").textContent = "Crear jornada";
    el("cancel-jornada-edit").hidden = true;
  }
  function resetMatch() {
    matchForm.reset();
    el("schedule-match-id").value = "";
    el("schedule-jornada").value = selected;
    el("schedule-form-title").textContent = "Programar partido";
    el("cancel-schedule-edit").hidden = true;
    applyMatchLocks();
  }
  function button(text, action, disabled = false) {
    const node = document.createElement("button");
    node.type = "button";
    node.className = "secondary-button";
    node.textContent = text;
    if (["Editar", "Eliminar"].includes(text)) decorateAdminTool(node, text);
    node.disabled = disabled || busy;
    node.addEventListener("click", () => { if (!busy) action(); });
    return node;
  }
  function confirmDelete(path, text) {
    pendingDelete = path;
    el("schedule-delete-text").textContent = text;
    message("schedule-delete-message", "");
    dialog.showModal();
    el("cancel-schedule-delete").focus();
  }
  function render() {
    el("jornada-list").replaceChildren();
    for (const jornada of jornadas) {
      const row = document.createElement("li");
      const actions = document.createElement("div");
      actions.className = "schedule-actions";
      const select = button(`Jornada ${jornada.number}`, () => {
        selected = String(jornada.id);
        resetMatch();
        render();
      });
      select.setAttribute("aria-pressed", String(String(jornada.id) === selected));
      actions.append(select, button("Editar", () => {
        el("jornada-edit-id").value = jornada.id;
        el("jornada-number").value = jornada.number;
        el("jornada-form-title").textContent = "Editar jornada";
        el("cancel-jornada-edit").hidden = false;
        message("jornada-message", "");
        el("jornada-number").focus();
      }), button("Eliminar", () => confirmDelete(`/api/admin/jornadas/${jornada.id}`, `¿Eliminar la jornada ${jornada.number}?`)));
      row.append(actions);
      el("jornada-list").append(row);
    }
    const jornada = jornadas.find(j => String(j.id) === selected);
    el("scheduled-matches-heading").textContent = jornada ? `Partidos · Jornada ${jornada.number}` : "Partidos";
    el("scheduled-match-list").replaceChildren();
    if (!jornada?.games.length) {
      const row = document.createElement("li");
      row.textContent = "No hay partidos programados.";
      el("scheduled-match-list").append(row);
    }
    for (const match of jornada?.games || []) {
      const row = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = `${match.team1} vs ${match.team2}`;
      const detail = document.createElement("p");
      detail.textContent = `${match.startsAt ? dateFormat.format(new Date(match.startsAt)) : `Fecha por confirmar · ${match.time}`} · ${match.status === "finished" ? "Finalizado" : "Pendiente"}`;
      const actions = document.createElement("div");
      actions.className = "schedule-actions";
      const remove = button("Eliminar", () => confirmDelete(`/api/admin/matches/${match.id}`, `¿Eliminar el partido ${match.team1} vs ${match.team2}?`), locked(match));
      if (locked(match)) remove.title = "No se pueden eliminar partidos con resultados registrados.";
      actions.append(button("Editar", () => {
        el("schedule-match-id").value = match.id;
        el("schedule-jornada").value = jornada.id;
        el("schedule-team1").value = match.team1Id;
        el("schedule-team2").value = match.team2Id;
        el("schedule-date").value = match.date || "";
        el("schedule-time").value = match.time;
        el("schedule-form-title").textContent = "Editar partido";
        el("cancel-schedule-edit").hidden = false;
        message("scheduled-match-message", "");
        applyMatchLocks();
        el("schedule-date").focus();
      }), remove);
      row.append(title, detail, actions);
      el("scheduled-match-list").append(row);
    }
  }
  function options(select, items, prompt, previous) {
    select.replaceChildren(new Option(prompt, ""));
    for (const item of items) select.add(new Option(item.label, item.id));
    select.value = previous;
  }
  async function load() {
    message("schedule-message", "Cargando jornadas...");
    el("refresh-schedule").disabled = true;
    try {
      const responses = await Promise.all([adminFetch("/api/admin/jornadas"), adminFetch("/api/teams")]);
      if (responses.some(r => !r.ok)) throw new Error("No se pudieron cargar las jornadas.");
      const [data, teams] = await Promise.all(responses.map(r => r.json()));
      if (loadedTournament !== window.selectedTournamentId) {
        selected = "";
        resetJornada();
        resetMatch();
        loadedTournament = window.selectedTournamentId;
      }
      jornadas = data;
      if (!jornadas.some(j => String(j.id) === selected)) selected = String(jornadas[0]?.id || "");
      const previousJornada = jornadas.some(j => String(j.id) === el("schedule-jornada").value) ? el("schedule-jornada").value : selected;
      options(el("schedule-jornada"), jornadas.map(j => ({id:j.id,label:`Jornada ${j.number}`})), "Selecciona una jornada", previousJornada);
      for (const id of ["schedule-team1", "schedule-team2"]) {
        options(el(id), teams.map(t => ({id:t.id,label:t.name})), "Selecciona un equipo", el(id).value);
      }
      render();
      applyMatchLocks();
      message("schedule-message", jornadas.length ? "" : "No hay jornadas registradas.");
    } catch (error) {
      message("schedule-message", "No se pudieron cargar las jornadas. Inténtalo de nuevo.", true);
    } finally {
      el("refresh-schedule").disabled = busy;
    }
  }
  async function save(path, method, data, statusId, reset) {
    if (busy) return;
    setBusy(true);
    message(statusId, "Guardando...");
    try {
      const response = await adminFetch(path, {method, headers:{"Content-Type":"application/json", "X-CSRF-Token":csrfToken}, body:JSON.stringify(data)});
      const result = await response.json();
      if (!response.ok) { message(statusId, result.error || "No se pudieron guardar los cambios.", true); return; }
      if (result.jornada) {
        selected = String(result.jornada.id);
        if (!el("schedule-match-id").value) el("schedule-jornada").value = selected;
      }
      reset();
      await Promise.all([load(), refreshTeamRelatedData()]);
      message(statusId, result.message);
    } catch (error) {
      message(statusId, "No se pudieron guardar los cambios. Inténtalo de nuevo.", true);
    } finally { setBusy(false); render(); }
  }
  jornadaForm.addEventListener("submit", event => {
    event.preventDefault();
    const number = el("jornada-number").value;
    if (!/^\d+$/.test(number) || Number(number) < 1 || Number(number) > 2147483647) {
      message("jornada-message", "Introduce un número de jornada entero positivo válido.", true); return;
    }
    const id = el("jornada-edit-id").value;
    save(`/api/admin/jornadas${id ? `/${id}` : ""}`, id ? "PUT" : "POST", {number}, "jornada-message", resetJornada);
  });
  matchForm.addEventListener("submit", event => {
    event.preventDefault();
    const jornada = el("schedule-jornada").value;
    const data = {team1Id:el("schedule-team1").value, team2Id:el("schedule-team2").value, date:el("schedule-date").value, time:el("schedule-time").value};
    if (!jornada || !data.team1Id || !data.team2Id || !data.date || !data.time) {
      message("scheduled-match-message", "Selecciona una jornada, dos equipos, la fecha y la hora.", true); return;
    }
    if (data.team1Id === data.team2Id) { message("scheduled-match-message", "Un equipo no puede jugar contra sí mismo.", true); return; }
    const id = el("schedule-match-id").value;
    save(id ? `/api/admin/matches/${id}` : `/api/admin/jornadas/${jornada}/matches`, id ? "PUT" : "POST", data, "scheduled-match-message", resetMatch);
  });
  el("confirm-schedule-delete").addEventListener("click", async () => {
    if (!pendingDelete || busy) return;
    setBusy(true);
    message("schedule-delete-message", "Eliminando...");
    try {
      const response = await adminFetch(pendingDelete, {method:"DELETE", headers:{"X-CSRF-Token":csrfToken}});
      const data = await response.json();
      if (!response.ok) { message("schedule-delete-message", data.error || "No se pudo eliminar el registro.", true); return; }
      dialog.close();
      resetMatch();
      resetJornada();
      await Promise.all([load(), refreshTeamRelatedData()]);
      message("schedule-message", data.message);
    } catch (error) { message("schedule-delete-message", "No se pudo eliminar el registro. Inténtalo de nuevo.", true); }
    finally { setBusy(false); render(); }
  });
  dialog.addEventListener("cancel", event => { if (busy) event.preventDefault(); });
  el("cancel-schedule-delete").addEventListener("click", () => { if (!busy) dialog.close(); });
  el("cancel-jornada-edit").addEventListener("click", () => { resetJornada(); message("jornada-message", ""); });
  el("cancel-schedule-edit").addEventListener("click", () => { resetMatch(); message("scheduled-match-message", ""); });
  el("schedule-jornada").addEventListener("change", () => { selected = el("schedule-jornada").value; render(); });
  el("refresh-schedule").addEventListener("click", () => { if (!busy) load(); });
  window.addEventListener("league-data-changed", () => { if (!busy) load(); });
  load();
})();
