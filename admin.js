const API_URL = "";
const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
window.selectedTournamentId = null;
window.competitionQuery = () => window.selectedTournamentId ? `?tournament_id=${window.selectedTournamentId}` : "";

async function adminFetch(url, options = {}) {
  const target = new URL(url, window.location.origin);
  if (window.selectedTournamentId && (
    ["/api/teams", "/api/jornadas", "/api/standings", "/api/admin/stats"].includes(target.pathname) ||
    target.pathname.startsWith("/api/admin/jornadas") || target.pathname.startsWith("/api/admin/matches/")
  )) target.searchParams.set("tournament_id",window.selectedTournamentId);
  const response = await fetch(target.pathname + target.search, { ...options, credentials: "same-origin" });
  if (response.status === 401) {
    window.location.assign("/login?motivo=sesion");
    throw new Error("Tu sesión ha caducado. Inicia sesión de nuevo.");
  }
  return response;
}

const matchSelect = document.querySelector("#match-select");
const setCount = document.querySelector("#set-count");
const setsContainer = document.querySelector("#sets-container");
const resultForm = document.querySelector("#result-form");
const resultMessage = document.querySelector("#result-message");
const saveButton = document.querySelector("#save-result");

function decorateAdminTool(button, action) {
  const paths = action === "Editar"
    ? ["M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z", "m15 5 4 4"]
    : ["M10 11v6M14 11v6M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"];
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [key, value] of Object.entries({ width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" })) icon.setAttribute(key, value);
  for (const d of paths) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d); icon.append(path);
  }
  button.setAttribute("aria-label", button.getAttribute("aria-label") || action);
  button.title = button.getAttribute("aria-label");
  button.classList.add("tool-button");
  if (action === "Eliminar") button.classList.add("delete-tool");
  button.replaceChildren(icon);
}

let matches = [];

async function loadDashboardStats() {
  try {
    const response = await adminFetch(`${API_URL}/api/admin/stats`);

    if (!response.ok) {
      throw new Error("No se pudieron cargar las estadísticas.");
    }

    const stats = await response.json();

    document.querySelector("#teams p").textContent = stats.teams;
    document.querySelector("#matches p").textContent = stats.jornadas;
    document.querySelector("#results p").textContent = stats.matches;
  } catch (error) {
    console.error("Error loading dashboard:", error);
    showMessage("No se pudieron cargar las estadísticas. Inténtalo de nuevo.", true);
  }
}

function showMessage(message, isError = false) {
  resultMessage.textContent = message;
  resultMessage.className = isError ? "message-error" : "message-success";
}

function renderSetInputs(existingSets = []) {
  setsContainer.replaceChildren();

  const count = Number(setCount.value);
  const match = matches.find((item) => String(item.id) === matchSelect.value);

  const team1 = match?.team1 || "Equipo 1";
  const team2 = match?.team2 || "Equipo 2";

  for (let index = 0; index < count; index++) {
    const set = existingSets[index] || {};

    const wrapper = document.createElement("div");
    wrapper.className = "set-row";

    const heading = document.createElement("h3");
    heading.textContent = `Set ${index + 1}`;

    const label1 = document.createElement("label");
    label1.textContent = team1;
    label1.htmlFor = `set-${index + 1}-team1`;

    const input1 = document.createElement("input");
    input1.type = "number";
    input1.id = label1.htmlFor;
    input1.inputMode = "numeric";
    input1.autocomplete = "off";
    input1.min = "0";
    input1.step = "1";
    input1.required = true;
    input1.className = "team1-points";
    input1.value = set.team1Points ?? "";

    const label2 = document.createElement("label");
    label2.textContent = team2;
    label2.htmlFor = `set-${index + 1}-team2`;

    const input2 = document.createElement("input");
    input2.type = "number";
    input2.id = label2.htmlFor;
    input2.inputMode = "numeric";
    input2.autocomplete = "off";
    input2.min = "0";
    input2.step = "1";
    input2.required = true;
    input2.className = "team2-points";
    input2.value = set.team2Points ?? "";

    const field1 = document.createElement("div");
    field1.className = "score-field";
    field1.append(label1, input1);

    const field2 = document.createElement("div");
    field2.className = "score-field";
    field2.append(label2, input2);

    wrapper.append(heading, field1, field2);

    setsContainer.appendChild(wrapper);
  }
}

function loadSelectedMatch() {
  showMessage("");

  const match = matches.find((item) => String(item.id) === matchSelect.value);

  if (!match) {
    renderSetInputs();
    return;
  }

  const existingSets = match.results?.sets || [];
  const bestOf = match.bestOf ?? 5;
  const needed = Math.floor(bestOf / 2) + 1;
  setCount.replaceChildren();
  for (let count = needed; count <= bestOf; count++) {
    setCount.add(new Option(`${count} sets`, String(count)));
  }
  if (existingSets.length >= needed && existingSets.length <= bestOf) {
    setCount.value = String(existingSets.length);
  } else {
    setCount.value = String(needed);
  }

  renderSetInputs(existingSets);
}

async function loadMatches() {
  try {
    const response = await adminFetch(`${API_URL}/api/jornadas`);

    if (!response.ok) {
      throw new Error("No se pudieron cargar los partidos.");
    }

    const jornadas = await response.json();

    matches = jornadas.flatMap((jornada) =>
      jornada.games.map((game) => ({
        ...game,
        jornadaNumber: jornada.number,
      })),
    );

    matchSelect.replaceChildren();

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Selecciona un partido";
    matchSelect.appendChild(placeholder);

    for (const match of matches) {
      const option = document.createElement("option");

      option.value = match.id;
      option.textContent =
        `Jornada ${match.jornadaNumber} — ` +
        `${match.team1} vs ${match.team2}` +
        (match.status === "finished" ? " (Finalizado)" : "");

      matchSelect.appendChild(option);
    }

    renderSetInputs();
  } catch (error) {
    console.error("Error loading matches:", error);
    showMessage("No se pudieron cargar los partidos. Inténtalo de nuevo.", true);
  }
}

function collectSets() {
  return [...setsContainer.querySelectorAll(".set-row")].map((row) => {
    const points1 = row.querySelector(".team1-points").value;
    const points2 = row.querySelector(".team2-points").value;

    return {
      team1Points: Number(points1),
      team2Points: Number(points2),
    };
  });
}

async function saveResult(event) {
  event.preventDefault();

  const matchId = matchSelect.value;

  if (!matchId) {
    showMessage("Selecciona un partido.", true);
    matchSelect.focus();
    return;
  }

  for (const input of setsContainer.querySelectorAll("input")) {
    if (input.value === "" || !input.validity.valid) {
      showMessage("Introduce un número entero mayor o igual a cero para los puntos de cada equipo.", true);
      input.focus();
      return;
    }
  }

  const sets = collectSets();

  saveButton.disabled = true;
  showMessage("Guardando resultado...");

  try {
    const response = await adminFetch(
      `${API_URL}/api/admin/matches/${matchId}/result`,
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({ sets }),
      },
    );

    const data = await response.json();

    if (!response.ok) {
      showMessage(data.error || "No se pudo guardar el resultado.", true);
      return;
    }

    showMessage("Resultado guardado correctamente.");

    await loadDashboardStats();
    await loadMatches();
    window.dispatchEvent(new Event("league-data-changed"));

    matchSelect.value = matchId;
    loadSelectedMatch();

    showMessage("Resultado guardado correctamente.");
  } catch (error) {
    console.error("Error saving result:", error);
    showMessage("No se pudo guardar el resultado. Inténtalo de nuevo.", true);
  } finally {
    saveButton.disabled = false;
  }
}

matchSelect.addEventListener("change", loadSelectedMatch);

setCount.addEventListener("change", () => {
  const existingSets = [...setsContainer.querySelectorAll(".set-row")].map(
    (row) => ({
      team1Points: row.querySelector(".team1-points").value,
      team2Points: row.querySelector(".team2-points").value,
    }),
  );

  renderSetInputs(existingSets);
});

resultForm.addEventListener("submit", saveResult);

loadDashboardStats();
loadMatches();

const teamForm = document.querySelector("#team-form");
const teamIdInput = document.querySelector("#team-id");
const teamNameInput = document.querySelector("#team-name");
const teamLogoInput = document.querySelector("#team-logo");
const currentTeamLogo = document.querySelector("#team-current-logo");
const removeLogoField = document.querySelector("#remove-logo-field");
const removeTeamLogo = document.querySelector("#remove-team-logo");
const teamFormTitle = document.querySelector("#team-form-title");
const saveTeamButton = document.querySelector("#save-team");
const cancelTeamEdit = document.querySelector("#cancel-team-edit");
const teamList = document.querySelector("#admin-teams-list");
const teamListMessage = document.querySelector("#team-list-message");
const teamFormMessage = document.querySelector("#team-form-message");
const refreshTeamsButton = document.querySelector("#refresh-teams");
const deleteTeamDialog = document.querySelector("#delete-team-dialog");
const deleteTeamMessage = document.querySelector("#delete-team-message");
const confirmTeamDelete = document.querySelector("#confirm-team-delete");
const cancelTeamDelete = document.querySelector("#cancel-team-delete");
let managedTeams = [];
let teamBusy = false;
let deletingTeam = null;

function teamMessage(element, text, isError = false) {
  element.textContent = text;
  element.className = isError ? "message-error" : "message-success";
}

function setTeamBusy(busy) {
  teamBusy = busy;
  teamForm.setAttribute("aria-busy", String(busy));
  for (const control of document.querySelectorAll("#team-management input, #team-management button, #delete-team-dialog button")) {
    control.disabled = busy;
  }
}

function resetTeamForm() {
  teamForm.reset();
  document.querySelector("#team-file-name").textContent = "Ningún archivo seleccionado";
  teamIdInput.value = "";
  teamFormTitle.textContent = "Registrar equipo";
  saveTeamButton.textContent = "Registrar equipo";
  cancelTeamEdit.hidden = true;
  currentTeamLogo.hidden = true;
  currentTeamLogo.removeAttribute("src");
  removeLogoField.hidden = true;
}

function editTeam(team) {
  if (teamBusy) return;
  resetTeamForm();
  teamMessage(teamFormMessage, "");
  teamIdInput.value = team.id;
  teamNameInput.value = team.name;
  teamFormTitle.textContent = "Editar equipo";
  saveTeamButton.textContent = "Guardar cambios";
  cancelTeamEdit.hidden = false;
  removeLogoField.hidden = !team.logo;
  if (team.logo) {
    currentTeamLogo.src = team.logo;
    currentTeamLogo.hidden = false;
  }
  teamForm.scrollIntoView({ block: "start" });
  teamNameInput.focus({ preventScroll: true });
}

function requestTeamDeletion(team) {
  if (teamBusy) return;
  deletingTeam = team;
  deleteTeamMessage.textContent = "";
  document.querySelector("#delete-team-confirmation").textContent =
    `¿Eliminar el equipo «${team.name}»? Esta acción no se puede deshacer.`;
  deleteTeamDialog.showModal();
  cancelTeamDelete.focus();
}

function renderManagedTeams() {
  teamList.replaceChildren();
  for (const team of managedTeams) {
    const row = document.createElement("li");
    row.className = "admin-team-row";
    if (team.logo) {
      const logo = document.createElement("img");
      logo.className = "admin-team-logo";
      logo.src = team.logo;
      logo.alt = `Logotipo de ${team.name}`;
      logo.width = 48;
      logo.height = 48;
      logo.loading = "lazy";
      row.append(logo);
    } else {
      const placeholder = document.createElement("span");
      placeholder.className = "admin-team-logo admin-team-placeholder";
      placeholder.textContent = team.name.charAt(0).toUpperCase();
      placeholder.setAttribute("aria-hidden", "true");
      row.append(placeholder);
    }
    const name = document.createElement("p");
    name.className = "admin-team-name";
    name.textContent = team.name;
    row.append(name);
    const actions = document.createElement("div");
    actions.className = "team-row-actions";
    for (const [label, handler] of [["Editar", editTeam], ["Eliminar", requestTeamDeletion]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary-button";
      button.textContent = label;
      button.setAttribute("aria-label", `${label} ${team.name}`);
      decorateAdminTool(button, label);
      button.disabled = teamBusy;
      button.addEventListener("click", () => handler(team));
      actions.append(button);
    }
    row.append(actions);
    teamList.append(row);
  }
}

async function loadManagedTeams() {
  teamMessage(teamListMessage, "Cargando equipos...");
  refreshTeamsButton.disabled = true;
  try {
    const response = await adminFetch("/api/admin/teams");
    if (!response.ok) {
      teamMessage(teamListMessage, "No se pudieron cargar los equipos. Inténtalo de nuevo.", true);
      return;
    }
    const data = await response.json();
    if (!Array.isArray(data)) throw new Error("Respuesta no válida.");
    managedTeams = data;
    renderManagedTeams();
    teamMessage(teamListMessage, managedTeams.length ? "" : "No hay equipos registrados.");
  } catch (error) {
    console.error("No se pudieron cargar los equipos:", error);
    teamMessage(teamListMessage, "No se pudieron cargar los equipos. Inténtalo de nuevo.", true);
  } finally {
    refreshTeamsButton.disabled = teamBusy;
  }
}

async function refreshTeamRelatedData() {
  const selectedMatch = matchSelect.value;
  const count = setCount.value;
  const draft = [...setsContainer.querySelectorAll(".set-row")].map(row => ({
    team1Points: row.querySelector(".team1-points").value,
    team2Points: row.querySelector(".team2-points").value,
  }));
  await Promise.all([loadManagedTeams(), loadDashboardStats(), loadMatches()]);
  matchSelect.value = selectedMatch;
  setCount.value = count;
  renderSetInputs(draft);
  window.dispatchEvent(new Event("league-data-changed"));
}

teamForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (teamBusy) return;
  if (!teamNameInput.value.trim()) {
    teamMessage(teamFormMessage, "Introduce el nombre del equipo.", true);
    teamNameInput.focus();
    return;
  }
  const file = teamLogoInput.files[0];
  if (file && (file.size > 2 * 1024 * 1024 || (file.type && !["image/jpeg", "image/png", "image/webp"].includes(file.type)))) {
    teamMessage(teamFormMessage, "Elige una imagen JPEG, PNG o WebP de hasta 2 MB.", true);
    return;
  }
  const id = teamIdInput.value;
  const data = new FormData();
  data.append("name", teamNameInput.value.trim());
  data.append("remove_logo", String(removeTeamLogo.checked));
  if (file) data.append("logo", file);
  setTeamBusy(true);
  teamMessage(teamFormMessage, "Guardando equipo...");
  try {
    const response = await adminFetch(id ? `/api/admin/teams/${id}` : "/api/admin/teams", {
      method: id ? "PUT" : "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: data,
    });
    const result = await response.json();
    if (!response.ok) {
      teamMessage(teamFormMessage, result.error || "No se pudo guardar el equipo.", true);
      return;
    }
    resetTeamForm();
    teamMessage(teamFormMessage, result.message);
    await refreshTeamRelatedData();
  } catch (error) {
    console.error("No se pudo guardar el equipo:", error);
    teamMessage(teamFormMessage, "No se pudo guardar el equipo. Inténtalo de nuevo.", true);
  } finally {
    setTeamBusy(false);
  }
});

confirmTeamDelete.addEventListener("click", async () => {
  if (teamBusy || !deletingTeam) return;
  setTeamBusy(true);
  deleteTeamMessage.textContent = "Eliminando equipo...";
  try {
    const response = await adminFetch(`/api/admin/teams/${deletingTeam.id}`, {
      method: "DELETE", headers: { "X-CSRF-Token": csrfToken },
    });
    const result = await response.json();
    if (!response.ok) {
      deleteTeamMessage.textContent = result.error || "No se pudo eliminar el equipo.";
      return;
    }
    if (teamIdInput.value === String(deletingTeam.id)) resetTeamForm();
    deleteTeamDialog.close();
    teamMessage(teamFormMessage, result.message);
    await refreshTeamRelatedData();
  } catch (error) {
    console.error("No se pudo eliminar el equipo:", error);
    deleteTeamMessage.textContent = "No se pudo eliminar el equipo. Inténtalo de nuevo.";
  } finally {
    setTeamBusy(false);
  }
});

cancelTeamDelete.addEventListener("click", () => deleteTeamDialog.close());
deleteTeamDialog.addEventListener("cancel", event => { if (teamBusy) event.preventDefault(); });
cancelTeamEdit.addEventListener("click", () => { resetTeamForm(); teamMessage(teamFormMessage, ""); });
refreshTeamsButton.addEventListener("click", loadManagedTeams);
removeTeamLogo.addEventListener("change", () => {
  if (removeTeamLogo.checked) teamLogoInput.value = "";
  currentTeamLogo.hidden = removeTeamLogo.checked || !currentTeamLogo.getAttribute("src");
});
teamLogoInput.addEventListener("change", () => {
  document.querySelector("#team-file-name").textContent = teamLogoInput.files[0]?.name || "Ningún archivo seleccionado";
  if (teamLogoInput.files.length) removeTeamLogo.checked = false;
});
loadManagedTeams();

function initAdminNavigation() {
  const nav = document.getElementById("admin-nav");
  const links = nav.querySelectorAll("a");
  function select() {
    const hash = window.location.hash || "#panel";
    links.forEach(link => {
      const active = link.hash === hash;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  }
  nav.addEventListener("click", event => {
    const link = event.target.closest("a");
    if (link) document.getElementById(link.hash.slice(1))?.focus({ preventScroll: true });
  });
  window.addEventListener("hashchange", select);
  select();
}
initAdminNavigation();
