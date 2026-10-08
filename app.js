const teams = [
    {
        name: "Los Abusadores",
        wins: 0,
        losses: 0,
        setsFor: 0,
        setsAgainst: 0,
        logo: "media/los_abusadores.JPG"

    },
    {
        name: "Los Lobos",
        wins: 0,
        losses: 0,
        setsFor: 0,
        setsAgainst: 0,
        logo: "media/los_lobos.JPG"
    },
    {
        name: "Los Defensores",
        wins: 0,
        losses: 0,
        setsFor: 0,
        setsAgainst: 0,
        logo: "media/polea.JPG"
    },
    {
        name: "La Furia Roja",
        wins: 0,
        losses: 0,
        setsFor: 0,
        setsAgainst: 0,
        logo: "media/la_furia_roja.JPG"
    },
    {
        name: "La Ofensiva Aplastante",
        wins: 0,
        losses: 0,
        setsFor: 0,
        setsAgainst: 0,
        logo: "media/la_ofensiva_aplastante.JPG"
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

// Functions

function calculateSets(results) {
  if (!isValidMatch(results)) {
    return {
      team1Sets: 0,
      team2Sets: 0,
    };
  }

  let team1Sets = 0;
  let team2Sets = 0;

  results.sets.forEach(function (set, index) {
    const setNumber = index + 1;

    if (!isValidSet(set, setNumber)) {
      return;
    }

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

function isValidSet(set, setNumber) {
    const pointsToWin = setNumber === 5 ? 15 : 25;

    const team1Wins = set.team1Points >= pointsToWin &&
                      set.team1Points - set.team2Points >= 2;

    const team2Wins = set.team2Points >= pointsToWin &&
                      set.team2Points - set.team1Points >= 2;

    return team1Wins || team2Wins;
}

function isValidMatch(results) {
  const sets = results.sets;

  if (sets.length < 3 || sets.length > 5) {
    return false;
  }

  let team1Sets = 0;
  let team2Sets = 0;

  sets.forEach(function (set, index) {
    const setNumber = index + 1;

    if (!isValidSet(set, setNumber)) {
      return;
    }

    if (set.team1Points > set.team2Points) {
      team1Sets++;
    } else {
      team2Sets++;
    }
  });

  if (team1Sets >= 3 || team2Sets >= 3) {
    return true;
  }

  return false;
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

// STANDINGS 

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

    teamCard.classList.add("team-card");

    const teamStats = table[team.name];
    
    const teamPosition = standingsArray.findIndex(function (standing) {
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
    
    const upcomingMatches = teamGames.filter(function (game) {
        return game.status !== "finished";
    });

  teamCard.innerHTML = `
    <button class="team-header" type="button">
        <div>
            <div class="team-title">
    <img src="${team.logo}" alt="${team.name}">
    <h3>${team.name}</h3>
</div>

            <p>
                Posición: ${teamPosition}
            </p>

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
            Partidos pendientes: ${upcomingMatches.length}
        </p>

        <p>
            Sets AF: ${teamStats.setsFor}
            |
            Sets EN: ${teamStats.setsAgainst}
        </p>

        <h4>
            Partidos
        </h4>

    </div>
`;
    const teamHeader = teamCard.querySelector(".team-header");
    const teamToggle = teamCard.querySelector(".team-toggle");

    teamHeader.addEventListener("click", function () {
      teamCard.classList.toggle("expanded");

      if (teamCard.classList.contains("expanded")) {
        teamToggle.textContent = "▲";
      } else {
        teamToggle.textContent = "▼";
      }
    });

    teamGames.forEach(function (game) {
      
    const statusClass = game.status || "scheduled";
        const matchElement = document.createElement("div");
        let opponent;

        if (game.team1 === team.name) {
            opponent = game.team2;
        } else {
            opponent = game.team1;  
        }

    matchElement.classList.add("match-card");

    matchElement.innerHTML = `
        <p>${game.time}</p>

        <h4>${game.team1} vs ${game.team2}</h4>

        <span class="game-status ${statusClass}">
            ${getStatusText(game.status)}
        </span>
    `;

        if (game.status !== "finished") {
          matchElement.innerHTML += `
        <p>
            Próximo rival: ${opponent}
        </p>
    `;
        }

   if (game.status === "finished") {
     const result = calculateSets(game.results);

     let teamResult;

     if (game.team1 === team.name) {
       if (result.team1Sets > result.team2Sets) {
         teamResult = "Victoria";
       } else {
         teamResult = "Derrota";
       }
     } else {
       if (result.team2Sets > result.team1Sets) {
         teamResult = "Victoria";
       } else {
         teamResult = "Derrota";
       }
     }

     matchElement.innerHTML += `
        <p>
            ${teamResult}
        </p>

        <p>
            Resultado: ${result.team1Sets} - ${result.team2Sets}
        </p>

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
   }

    const teamDetails = teamCard.querySelector(".team-details");

    teamDetails.appendChild(matchElement);

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
        }

        jornadaElement.appendChild(matchElement);
    });

    upcomingMatches.appendChild(jornadaElement);
});
