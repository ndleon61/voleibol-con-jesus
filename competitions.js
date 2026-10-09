(() => {
  const el = id => document.getElementById(id);
  const labels = {planned:"Planificado",active:"En curso",completed:"Completado",archived:"Archivado"};
  let seasons = [], tournaments = [], busy = false, selectedSeason = null;
  function message(text,error=false) {
    el("competition-message").textContent=text;
    el("competition-message").className=error?"message-error":"message-success";
  }
  function options(id,rows,selected,prompt) {
    el(id).replaceChildren(new Option(prompt,""));
    for(const row of rows) el(id).add(new Option(`${row.name}${row.status?` · ${labels[row.status]}`:""}${row.isPublic?" · Público":""}`,row.id));
    el(id).value=selected || "";
  }
  function fill(prefix,row) {
    el(`${prefix}-name`).value=row?.name || "";
    el(`${prefix}-start`).value=row?.startDate || "";
    el(`${prefix}-end`).value=row?.endDate || "";
    el(`${prefix}-status`).value=row?.status || "planned";
  }
  function dates(prefix) { return {name:el(`${prefix}-name`).value,startDate:el(`${prefix}-start`).value || null,endDate:el(`${prefix}-end`).value || null,status:el(`${prefix}-status`).value}; }
  async function read(url) {
    const r=await adminFetch(url);
    const data=await r.json();
    if(!r.ok) throw new Error(data.error || "No se pudieron cargar las competiciones.");
    return data;
  }
  async function views() {
    const id=window.selectedTournamentId;
    el("registration-list").replaceChildren();
    el("competition-standings").replaceChildren();
    if(!id) return;
    const [registered,catalog,standings]=await Promise.all([read(`/api/admin/tournaments/${id}/teams`),read("/api/admin/teams"),read(`/api/tournaments/${id}/standings`)]);
    options("registration-team",catalog.filter(t=>!registered.some(r=>r.id===t.id)),null,"Selecciona un equipo");
    const closed=["completed","archived"].includes(tournaments.find(t=>t.id===id)?.status);
    for(const team of registered) {
      const row=document.createElement("li");
      const name=document.createElement("span"); name.textContent=team.name;
      const remove=document.createElement("button"); remove.type="button"; remove.className="secondary-button"; remove.textContent="Retirar inscripción"; remove.disabled=closed;
      remove.addEventListener("click",()=> { if(window.confirm(`¿Retirar la inscripción de ${team.name}?`)) mutate(`/api/admin/tournaments/${id}/teams/${team.id}`,"DELETE"); });
      row.append(name,document.createTextNode(" "),remove); el("registration-list").append(row);
    }
    for(const team of standings) {
      const row=document.createElement("li");
      row.textContent=`${team.team} · ${team.wins} victorias · ${team.losses} derrotas · Sets ${team.setsWon}-${team.setsLost}`;
      el("competition-standings").append(row);
    }
  }
  async function load() {
    message("Cargando temporadas y torneos...");
    [seasons,tournaments]=await Promise.all([read("/api/admin/seasons"),read("/api/admin/tournaments")]);
    if(!window.selectedTournamentId) window.selectedTournamentId=tournaments.find(t=>t.isPublic)?.id || null;
    const selected=tournaments.find(t=>t.id===window.selectedTournamentId);
    options("season-select",seasons,selectedSeason || el("season-select").value || selected?.seasonId,"Nueva temporada");
    options("tournament-season",seasons,selected?.seasonId || el("season-select").value,"Selecciona una temporada");
    options("tournament-select",tournaments,window.selectedTournamentId,"Nuevo torneo");
    fill("season",seasons.find(s=>String(s.id)===el("season-select").value));
    fill("tournament",selected);
    el("activate-tournament").disabled=!selected || ["completed","archived"].includes(selected.status);
    el("tournament-season").disabled=Boolean(selected);
    await views();
    message("");
  }
  async function mutate(url,method,data) {
    if(busy) return;
    busy=true;
    for(const button of document.querySelectorAll("#competition-management button")) button.disabled=true;
    message("Guardando...");
    try {
      const response=await adminFetch(url,{method,headers:{"Content-Type":"application/json","X-CSRF-Token":csrfToken},...(data?{body:JSON.stringify(data)}:{})});
      const result=await response.json();
      if(!response.ok) throw new Error(result.error || "No se pudieron guardar los cambios.");
      if(result.tournament) window.selectedTournamentId=result.tournament.id;
      if(result.season) selectedSeason=result.season.id;
      await load();
      await Promise.all([loadMatches(),loadDashboardStats()]);
      window.dispatchEvent(new Event("league-data-changed"));
      message(result.message);
    } catch(error) { message(error.message,true); }
    finally {
      busy=false;
      for(const button of document.querySelectorAll("#competition-management button")) button.disabled=false;
      const selected=tournaments.find(t=>t.id===window.selectedTournamentId);
      el("activate-tournament").disabled=!selected || ["completed","archived"].includes(selected.status);
      if(["completed","archived"].includes(selected?.status)) {
        for(const button of el("registration-list").querySelectorAll("button")) button.disabled=true;
      }
    }
  }
  el("season-select").addEventListener("change",()=>{selectedSeason=el("season-select").value || null;fill("season",seasons.find(s=>String(s.id)===el("season-select").value));});
  el("new-season").addEventListener("click",()=>{selectedSeason=null;el("season-select").value="";fill("season");});
  el("new-tournament").addEventListener("click",()=>{el("tournament-select").value="";el("tournament-season").disabled=false;el("tournament-season").value=el("season-select").value;fill("tournament");});
  el("tournament-select").addEventListener("change",async()=>{
    if(!el("tournament-select").value) {fill("tournament");el("tournament-season").disabled=false;return;}
    if(matchSelect.value && !window.confirm("¿Cambiar de torneo? Se descartará el resultado sin guardar.")) {el("tournament-select").value=window.selectedTournamentId || "";return;}
    window.selectedTournamentId=Number(el("tournament-select").value);
    try {await load();await Promise.all([loadMatches(),loadDashboardStats()]);window.dispatchEvent(new Event("league-data-changed"));}
    catch(error) {message(error.message,true);}
  });
  el("season-form").addEventListener("submit",event=>{event.preventDefault();const id=el("season-select").value;mutate(`/api/admin/seasons${id?`/${id}`:""}`,id?"PUT":"POST",dates("season"));});
  el("tournament-form").addEventListener("submit",event=>{event.preventDefault();const id=el("tournament-select").value;mutate(`/api/admin/tournaments${id?`/${id}`:""}`,id?"PUT":"POST",{...dates("tournament"),seasonId:el("tournament-season").value});});
  el("registration-form").addEventListener("submit",event=>{event.preventDefault();if(!window.selectedTournamentId){message("Selecciona un torneo.",true);return;}mutate(`/api/admin/tournaments/${window.selectedTournamentId}/teams`,"POST",{teamId:el("registration-team").value});});
  el("activate-tournament").addEventListener("click",()=>{if(window.selectedTournamentId) mutate(`/api/admin/tournaments/${window.selectedTournamentId}/activate`,"POST");});
  el("refresh-competitions").addEventListener("click",()=>load().catch(error=>message(error.message,true)));
  window.addEventListener("league-data-changed",()=>{if(!busy) views().catch(error=>message(error.message,true));});
  load().catch(error=>message(error.message,true));
})();
