const teamsMetadata = [
  {
    name: "Los Abusadores",
    wins: 0,
    losses: 0,
    setsFor: 0,
    setsAgainst: 0,
    logo: "media/los_abusadores.JPG",
  },
  {
    name: "Los Lobos",
    wins: 0,
    losses: 0,
    setsFor: 0,
    setsAgainst: 0,
    logo: "media/los_lobos.JPG",
  },
  {
    name: "Los Defensores",
    wins: 0,
    losses: 0,
    setsFor: 0,
    setsAgainst: 0,
    logo: "media/polea.JPG",
  },
  {
    name: "La Furia Roja",
    wins: 0,
    losses: 0,
    setsFor: 0,
    setsAgainst: 0,
    logo: "media/la_furia_roja.JPG",
  },
  {
    name: "La Ofensiva Aplastante",
    wins: 0,
    losses: 0,
    setsFor: 0,
    setsAgainst: 0,
    logo: "media/la_ofensiva_aplastante.JPG",
  },
];

// Teams will be loaded from the Express API.
let teams = [];
let jornadas = [];

// -------------------------------------
// MATCH VALIDATION AND CALCULATIONS
// -------------------------------------

function isValidSet(set, setNumber) {
  if (
    !set ||
    !Number.isFinite(set.team1Points) ||
    !Number.isFinite(set.team2Points)
  ) {
    return false;
  }

  const pointsToWin = setNumber === 5 ? 15 : 25;

  const team1Wins =
    set.team1Points >= pointsToWin && set.team1Points - set.team2Points >= 2;

  const team2Wins =
    set.team2Points >= pointsToWin && set.team2Points - set.team1Points >= 2;

  return team1Wins || team2Wins;
}

function isValidMatch(results) {
  if (
    !results ||
    !Array.isArray(results.sets) ||
    results.sets.length < 3 ||
    results.sets.length > 5
  ) {
    return false;
  }

  let team1Sets = 0;
  let team2Sets = 0;

  for (let index = 0; index < results.sets.length; index++) {
    const set = results.sets[index];
    const setNumber = index + 1;

    if (!isValidSet(set, setNumber)) {
      return false;
    }

    if (set.team1Points > set.team2Points) {
      team1Sets++;
    } else {
      team2Sets++;
    }

    // A valid best-of-five match ends as soon as a team wins 3 sets.
    if (team1Sets === 3 || team2Sets === 3) {
      return index === results.sets.length - 1;
    }
  }

  return false;
}

function calculateSets(results) {
  if (!isValidMatch(results)) {
    return {
      team1Sets: 0,
      team2Sets: 0,
    };
  }

  let team1Sets = 0;
  let team2Sets = 0;

  results.sets.forEach(function (set) {
    if (set.team1Points > set.team2Points) {
      team1Sets++;
    } else {
      team2Sets++;
    }
  });

  return {
    team1Sets: team1Sets,
    team2Sets: team2Sets,
  };
}

function getStatusText(status) {
  if (status === "live") {
    return "En vivo";
  }

  if (status === "finished") {
    return "Finalizado";
  }

  return "Próximo";
}

// -------------------------------------
// CALCULATE STANDINGS
// -------------------------------------

function calculateStandings() {
  const table = {};

  teams.forEach(function (team) {
    table[team.name] = {
      name: team.name,
      wins: 0,
      losses: 0,
      setsFor: 0,
      setsAgainst: 0,
    };
  });

  jornadas.forEach(function (jornada) {
    jornada.games.forEach(function (game) {
      if (game.status !== "finished") {
        return;
      }

      // Ignore games with missing teams or invalid results.
      if (
        !table[game.team1] ||
        !table[game.team2] ||
        !isValidMatch(game.results)
      ) {
        console.warn(
          "Match skipped in standings because its result is invalid:",
          game.team1,
          "vs",
          game.team2,
        );
        return;
      }

      const result = calculateSets(game.results);
      const team1 = table[game.team1];
      const team2 = table[game.team2];

      team1.setsFor += result.team1Sets;
      team1.setsAgainst += result.team2Sets;

      team2.setsFor += result.team2Sets;
      team2.setsAgainst += result.team1Sets;

      if (result.team1Sets > result.team2Sets) {
        team1.wins++;
        team2.losses++;
      } else {
        team2.wins++;
        team1.losses++;
      }
    });
  });

  return table;
}

// -------------------------------------
// RENDER THE WEBSITE
// This runs only after teams load.
// -------------------------------------

function renderApp() {
  const standings = document.getElementById("standings");
  const resultsContainer = document.getElementById("results");
  const teamsContainer = document.getElementById("teams");
  const upcomingMatchesContainer = document.getElementById("upcoming-matches");

  if (
    !standings ||
    !resultsContainer ||
    !teamsContainer ||
    !upcomingMatchesContainer
  ) {
    console.error(
      "One or more required HTML elements are missing. " +
        "Check the IDs in index.html.",
    );
    return;
  }

  // ----- STANDINGS -----

  standings.innerHTML = "";

  const table = calculateStandings();
  const standingsArray = Object.values(table);

  standingsArray.sort(function (a, b) {
    // First: most wins.
    if (b.wins !== a.wins) {
      return b.wins - a.wins;
    }

    // Second: best set differential.
    const differenceA = a.setsFor - a.setsAgainst;
    const differenceB = b.setsFor - b.setsAgainst;

    return differenceB - differenceA;
  });

  standingsArray.forEach(function (team, index) {
    const row = document.createElement("tr");

    row.innerHTML = `
            <td>${index + 1}</td>
            <td>${team.name}</td>
            <td>${team.wins}</td>
            <td>${team.losses}</td>
            <td>${team.setsFor}</td>
            <td>${team.setsAgainst}</td>
        `;

    standings.appendChild(row);
  });

  // ----- RESULTS -----

  resultsContainer.innerHTML = "";

  jornadas.forEach(function (jornada) {
    jornada.games.forEach(function (game) {
      if (game.status !== "finished") {
        return;
      }

      const resultCard = document.createElement("div");
      resultCard.classList.add("match-card");

      const result = calculateSets(game.results);

      resultCard.innerHTML = `
                <h4>
                    ${game.team1} ${result.team1Sets} -
                    ${result.team2Sets} ${game.team2}
                </h4>

                <div class="set-scores">
                    ${(game.results?.sets || [])
                      .map(function (set, index) {
                        return `
                                <p>
                                    Set ${index + 1}:
                                    ${set.team1Points} -
                                    ${set.team2Points}
                                </p>
                            `;
                      })
                      .join("")}
                </div>
            `;

      resultsContainer.appendChild(resultCard);
    });
  });

  // ----- TEAM CARDS -----

  teamsContainer.innerHTML = "";

  teams.forEach(function (team) {
    const teamCard = document.createElement("div");
    teamCard.classList.add("team-card");

    const teamStats = table[team.name];

    const teamPosition =
      standingsArray.findIndex(function (standing) {
        return standing.name === team.name;
      }) + 1;

    const teamGames = [];

    jornadas.forEach(function (jornada) {
      jornada.games.forEach(function (game) {
        if (game.team1 === team.name || game.team2 === team.name) {
          teamGames.push(game);
        }
      });
    });

    const finishedMatches = teamGames.filter(function (game) {
      return game.status === "finished";
    });

    const pendingMatches = teamGames.filter(function (game) {
      return game.status !== "finished";
    });

    teamCard.innerHTML = `
            <button class="team-header" type="button">
                <div>
                    <div class="team-title">
                        <img src="${team.logo || ""}" alt="${team.name}">
                        <h3>${team.name}</h3>
                    </div>

                    <p>Posición: ${teamPosition}</p>

                    <p>
                        Victorias: ${teamStats.wins}
                        |
                        Derrotas: ${teamStats.losses}
                    </p>
                </div>

                <span class="team-toggle">▼</span>
            </button>

            <div class="team-details">
                <p>
                    Partidos jugados: ${finishedMatches.length}
                    |
                    Partidos pendientes: ${pendingMatches.length}
                </p>

                <p>
                    Sets AF: ${teamStats.setsFor}
                    |
                    Sets EN: ${teamStats.setsAgainst}
                </p>

                <h4>Partidos</h4>
            </div>
        `;

    const teamHeader = teamCard.querySelector(".team-header");
    const teamToggle = teamCard.querySelector(".team-toggle");
    const teamDetails = teamCard.querySelector(".team-details");

    teamHeader.addEventListener("click", function () {
      teamCard.classList.toggle("expanded");

      teamToggle.textContent = teamCard.classList.contains("expanded")
        ? "▲"
        : "▼";
    });

    teamGames.forEach(function (game) {
      const matchElement = document.createElement("div");
      matchElement.classList.add("match-card");

      const statusClass = game.status || "scheduled";

      const opponent = game.team1 === team.name ? game.team2 : game.team1;

      matchElement.innerHTML = `
                <p>${game.time}</p>

                <h4>${game.team1} vs ${game.team2}</h4>

                <span class="game-status ${statusClass}">
                    ${getStatusText(game.status)}
                </span>
            `;

      if (game.status !== "finished") {
        matchElement.innerHTML += `
                    <p>Próximo rival: ${opponent}</p>
                `;
      } else {
        const result = calculateSets(game.results);
        let teamResult = "Resultado no válido";

        if (isValidMatch(game.results)) {
          if (game.team1 === team.name) {
            teamResult =
              result.team1Sets > result.team2Sets ? "Victoria" : "Derrota";
          } else {
            teamResult =
              result.team2Sets > result.team1Sets ? "Victoria" : "Derrota";
          }
        }

        matchElement.innerHTML += `
                    <p>${teamResult}</p>

                    <p>
                        Resultado:
                        ${result.team1Sets} - ${result.team2Sets}
                    </p>

                    <div class="set-scores">
                        ${(game.results?.sets || [])
                          .map(function (set, index) {
                            return `
                                    <p>
                                        Set ${index + 1}:
                                        ${set.team1Points} -
                                        ${set.team2Points}
                                    </p>
                                `;
                          })
                          .join("")}
                    </div>
                `;
      }

      teamDetails.appendChild(matchElement);
    });

    teamsContainer.appendChild(teamCard);
  });

  // ----- UPCOMING MATCHES AND JORNADAS -----

  upcomingMatchesContainer.innerHTML = "";

  jornadas.forEach(function (jornada) {
    const jornadaElement = document.createElement("div");
    jornadaElement.classList.add("jornada-card");

    jornadaElement.innerHTML = `
            <h3>Jornada ${jornada.number}</h3>
        `;

    jornada.games.forEach(function (game) {
      const matchElement = document.createElement("div");
      matchElement.classList.add("match-card");

      const statusClass = game.status || "scheduled";

      matchElement.innerHTML = `
                <p class="match-time">${game.time}</p>

                <h4>
                    ${game.team1}
                    <span>vs</span>
                    ${game.team2}
                </h4>

                <span class="game-status ${statusClass}">
                    ${getStatusText(game.status)}
                </span>
            `;

      if (game.status === "finished") {
        const result = calculateSets(game.results);

        matchElement.innerHTML += `
                    <p>
                        Resultado:
                        ${result.team1Sets} - ${result.team2Sets}
                    </p>
                `;
      }

      jornadaElement.appendChild(matchElement);
    });

    upcomingMatchesContainer.appendChild(jornadaElement);
  });

  console.log("Website rendered successfully.");
}

// -------------------------------------
// LOAD TEAMS FROM FLASK API
// -------------------------------------


function loadTeams() {
  Promise.all([
    fetch("http://localhost:3000/api/teams"),
    fetch("http://localhost:3000/api/jornadas"),
  ])
    .then(function (responses) {
      responses.forEach(function (response) {
        if (!response.ok) {
          throw new Error("Server returned HTTP " + response.status);
        }
      });

      return Promise.all(
        responses.map(function (response) {
          return response.json();
        }),
      );
    })
    .then(function (data) {
      const teamsFromServer = data[0];
      const jornadasFromServer = data[1];

      if (!Array.isArray(teamsFromServer)) {
        throw new Error("The API did not return a team list.");
      }

      if (!Array.isArray(jornadasFromServer)) {
        throw new Error("The API did not return a jornada list.");
      }

      teams = teamsFromServer.map(function (apiTeam) {
        const localTeam = teamsMetadata.find(function (team) {
          return team.name === apiTeam.name;
        });

        if (!localTeam) {
          console.warn("No local logo metadata found for:", apiTeam.name);
        }

        return {
          ...(localTeam || {}),
          ...apiTeam,
        };
      });

      jornadas = jornadasFromServer;

      console.log("Teams loaded successfully:", teams);
      console.log("Jornadas loaded successfully:", jornadas);

      renderApp();
    })
    .catch(function (error) {
      console.error("Could not load website data from the API:", error);

      const teamsContainer = document.getElementById("teams");

      if (teamsContainer) {
        teamsContainer.innerHTML = `
          <p>
            No se pudieron cargar los datos.
            Comprueba que el servidor esté funcionando
            e inténtalo de nuevo.
          </p>
        `;
      }
    });
}

// Start the application.
loadTeams();
