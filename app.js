const teams = [
    {
        name: "Los Abusadores"
    },
    {
        name: "Los Lobos"
    },
    {
        name: "Polea"
    },
    {
        name: "La Furia Roja"
    },
    {
        name: "La Ofensiva Aplastante"
    }
];

const jornadas = [

    {
        number: 1,
        games: [
            {
                time: "5:30 PM",
                team1: "Los Abusadores",
                team2: "Los Lobos"
            },
            {
                time: "6:00 PM",
                team1: "Los Abusadores",
                team2: "Los Defensores"
            }
        ]
    }
   
]







const standings = document.getElementById("standings");

standings.innerHTML = "";
teams.forEach(function (team, index) {
  const row = document.createElement("tr");

  row.innerHTML = `
        <td>${index + 1}</td>
        <td>${team.name}</td>
        <td>0</td>
        <td>0</td>
        <td>0</td>
        <td>0</td>
    `;

  standings.appendChild(row);
});

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

        matchElement.classList.add("match-card");

        matchElement.innerHTML = `
        <p>${game.time}</p>
        <p>${game.team1} vs ${game.team2}</p>
        `;

        jornadaElement.appendChild(matchElement);
    });

    upcomingMatches.appendChild(jornadaElement);
});
