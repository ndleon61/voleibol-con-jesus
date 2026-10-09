
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

teams = [
    {"name": "Los Abusadores"},
    {"name": "Los Lobos"},
    {"name": "Los Defensores"},
    {"name": "La Furia Roja"},
    {"name": "La Ofensiva Aplastante"},
]


jornadas = [
    {
        "number": 1,
        "games": [
            {
                "time": "5:30 PM",
                "team1": "La Ofensiva Aplastante",
                "team2": "Los Lobos",
                "status": "",
            },
            {
                "time": "6:00 PM",
                "team1": "Los Abusadores",
                "team2": "Los Defensores",
                "status": "",
            },
        ],
    },
    {
        "number": 2,
        "games": [
            {
                "time": "5:30 PM",
                "team1": "Los Lobos",
                "team2": "Los Abusadores",
                "status": "",
            },
            {
                "time": "6:00 PM",
                "team1": "La Furia Roja",
                "team2": "La Ofensiva Aplastante",
                "status": "finished",
                "results": {
                    "sets": [
                        {"team1Points": 25, "team2Points": 20},
                        {"team1Points": 22, "team2Points": 25},
                        {"team1Points": 15, "team2Points": 10},
                        {"team1Points": 25, "team2Points": 20},
                    ],
                },
            },
        ],
    },
]

@app.route("/api/teams", methods=["GET"])
def get_teams():
    return jsonify(teams)

@app.route("/api/jornadas", methods=["GET"])
def get_jornadas():
    return jsonify(jornadas)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=3000, debug=True)