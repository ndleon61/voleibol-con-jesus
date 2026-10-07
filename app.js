const teams = [
    {
        name: "Los Abusadores",
        wins: 0,
        losses: 0,
        setsFor: 0,
        setsAgainst: 0
    },
    {
        name: "Los Lobos",
        wins: 0,
        losses: 0,
        setsFor: 0,
        setsAgainst: 0
    },
    {
        name: "Los Defensores",
        wins: 0,
        losses: 0,
        setsFor: 0,
        setsAgainst: 0
    },
    {
        name: "La Furia Roja",
        wins: 0,
        losses: 0,
        setsFor: 0,
        setsAgainst: 0
    },
    {
        name: "La Ofensiva Aplastante",
        wins: 0,
        losses: 0,
        setsFor: 0,
        setsAgainst: 0
    },

];

const jornadas = [

    {
        number: 1,
        games: [
            {
                time: "5:30 PM",
                team1: "La Ofensiva Aplastante",
                team2: "Los Lobos",
                status: ""
            },
            {
                time: "6:00 PM",
                team1: "Los Abusadores",
                team2: "Los Defensores",
                status: ""
            }
        ]
    },

    {
        number: 2,
        games: [
            {
                time: "5:30 PM",
                team1: "Los Lobos",
                team2: "Los Abusadores",
                status: ""
            },
            {
                time: "6:00 PM",
                team1: "La Furia Roja",
                team2: "La Ofensiva Aplastante",
                status: "finished",

                results: {
                    sets: [
                        {
                            team1Points: 25,
                            team2Points: 20
                        },
                        {
                            team1Points: 22,
                            team2Points: 25
                        },
                        {
                            team1Points: 15,
                            team2Points: 10
                        },
                        {
                            team1Points: 25,
                            team2Points: 20
                        }
                    ]
                }
            }
        ]
    },


   
]



function calculateSets(results) {
  let team1Sets = 0;
  let team2Sets = 0;

  results.sets.forEach(function (set) {
    if (set.team1Points > set.team2Points) {
      team1Sets++;
    }

    if (set.team2Points > set.team1Points) {
      team2Sets++;
    }
  });

  return {
    team1Sets,
    team2Sets,
  };
}

function getStatusText(status) {
  if (status === "live") {
    return "En vivo";
  } else if (status === "finished") {
    return "Finalizado";
  } else {
    return "Próximo";
  }
}

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

      const result = calculateSets(game.results);

      const team1 = table[game.team1];
      const team2 = table[game.team2];

      // Sets in favors and against
      team1.setsFor += result.team1Sets;
      team1.setsAgainst += result.team2Sets;

      team2.setsFor += result.team2Sets;
      team2.setsAgainst += result.team1Sets;

      // Victories and Defeats
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


const standings = document.getElementById("standings");

standings.innerHTML = "";

const table = calculateStandings();

const standingsArray = Object.values(table);

standingsArray.sort(function (a, b) {

    //First by more wins
    if (b.wins !== a.wins) {
        return b.wins - a.wins;
    }

    //Then by more sets in favor
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


const results = document.getElementById("results");

results.innerHTML = "";

jornadas.forEach(function (jornada) {
  jornada.games.forEach(function (game) {
    if (game.status !== "finished") {
      return;
    }

    const resultCard = document.createElement("div");

    resultCard.classList.add("match-card");

    const result = calculateSets(game.results);

    resultCard.innerHTML = `
            <h4>${game.team1} ${result.team1Sets} - ${result.team2Sets} ${game.team2}</h4>

            <div class="set-scores">
                ${game.results.sets
                  .map(function (set, index) {
                    return `
                        <p>
                            Set ${index + 1}: 
                            ${set.team1Points} - ${set.team2Points}
                        </p>
                    `;
                  })
                  .join("")}
            </div>
        `;

    results.appendChild(resultCard);
  });
});

// TEAM CONTAINER

const teamsContainer = document.getElementById("teams");

teamsContainer.innerHTML = "";

teams.forEach(function (team) {
  const teamCard = document.createElement("div");

  teamCard.classList.add("jornada-card");

  const table = calculateStandings();
  const teamStats = table[team.name];

  const teamGames = [];

  jornadas.forEach(function (jornada) {
    jornada.games.forEach(function (game) {
      if (game.team1 === team.name || game.team2 === team.name) {
        teamGames.push(game);
      }
    });
  });

  teamCard.innerHTML = `
        <h3>${team.name}</h3>

        <p>
            Victorias: ${teamStats.wins}
            |
            Derrotas: ${teamStats.losses}
        </p>

        <p>
            Sets AF: ${teamStats.setsFor}
            |
            Sets EN: ${teamStats.setsAgainst}
        </p>

        <h4>Partidos</h4>
    `;

  teamGames.forEach(function (game) {
    const statusClass = game.status || "scheduled";

    const matchElement = document.createElement("div");

    matchElement.classList.add("match-card");

    matchElement.innerHTML = `
        <p>${game.time}</p>

        <h4>${game.team1} vs ${game.team2}</h4>

        <span class="game-status ${statusClass}">
            ${getStatusText(game.status)}
        </span>
    `;

    if (game.status === "finished") {

        const result = calculateSets(game.results);

        matchElement.innerHTML += `
            <p>
                Resultado: ${result.team1Sets} - ${result.team2Sets}
            </p>

            <div class="set-scores">

                ${game.results.sets.map(function(set, index) {
                    return `
                        <p>
                            Set ${index + 1}: 
                            ${set.team1Points} - ${set.team2Points}
                        </p>
                    `;
                }).join("")}

            </div>
        `;
    }

    teamCard.appendChild(matchElement);

  });

  teamsContainer.appendChild(teamCard);
});


// UPCOMING MATCHES

const upcomingMatches = document.getElementById("upcoming-matches");
upcomingMatches.innerHTML = "";
jornadas.forEach(function (jornada) { 

    const jornadaElement = document.createElement("div");

    jornadaElement.classList.add("jornada-card");

    jornadaElement.innerHTML = `
    <h3>Jornada ${jornada.number}</h3>
    `;

    jornada.games.forEach(function (game) {
        const matchElement = document.createElement("div");
        const statusClass = game.status || "scheduled";

        matchElement.classList.add("match-card");

        matchElement.innerHTML = `
            <p>${game.time}</p>
            <p>${game.team1} vs ${game.team2}</p>
             <span class="game-status ${statusClass}">
             ${getStatusText(game.status)}
             </span>
    `;
        if (game.status === "finished") {

            const result = calculateSets(game.results);

            matchElement.innerHTML += `
                <p>
                    Resultado: ${result.team1Sets} - ${result.team2Sets}
                </p>

                <div class= "set-scores">
                    ${game.results.sets.map((set, index) => `
                        <p>
                            Set ${index + 1}: 
                            ${set.team1Points} - ${set.team2Points}  
                        </p>

                    `).join("")}
                
                </div>
            
            `;
        }

        jornadaElement.appendChild(matchElement);
    });

    upcomingMatches.appendChild(jornadaElement);
});
