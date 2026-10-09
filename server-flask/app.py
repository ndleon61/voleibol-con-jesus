
from pathlib import Path
import os
from flask import Flask, jsonify, request, send_from_directory, render_template
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
import psycopg
from auth import csrf_token, install_auth
from teams import install_teams
from scheduling import HAVANA, schedule_fields, install_scheduling
from competitions import install_competitions, requested_tournament, management_tournament, require_open, integrity_message
from configuration import settings
from reliability import checked_rows


PROJECT_ROOT = Path(__file__).resolve().parent.parent
app = Flask(__name__, template_folder=str(PROJECT_ROOT), static_folder=None)
app.config.update(settings())
production = app.config["PRODUCTION"]
if os.environ.get("TRUST_PROXY") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0)


@app.route("/")
def index():
    return send_from_directory(PROJECT_ROOT, "index.html")


@app.route("/<filename>")
def frontend_file(filename):
    if filename not in {"index.html", "admin.html", "app.js", "admin.js", "scheduling.js", "competitions.js", "styles.css", "admin.css"}:
        return jsonify({"error": "No se encontró la página."}), 404
    if filename == "admin.html":
        return render_template("admin.html", csrf_token=csrf_token())
    return send_from_directory(PROJECT_ROOT, filename)


@app.route("/media/<filename>")
def media_file(filename):
    return send_from_directory(PROJECT_ROOT / "media", filename)


def get_db_connection():
    return psycopg.connect(os.environ.get("DATABASE_URL", "dbname=voleibolcuba"), connect_timeout=5,
                           options="-c statement_timeout=15000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=30000")


@app.before_request
def validate_transport():
    # Host validation must precede authentication and session writes.
    request.host
    if app.config["PRODUCTION"] and not request.is_secure:
        return jsonify(error="Utiliza una conexión HTTPS segura."), 400


install_teams(app, lambda: get_db_connection())
install_auth(app, lambda: get_db_connection())
install_scheduling(app, lambda: get_db_connection())


@app.errorhandler(psycopg.Error)
def database_error(error):
    app.logger.error("Database request failed (%s)", type(error).__name__)
    return jsonify(error="El servicio no está disponible. Inténtalo de nuevo."), 503


@app.errorhandler(psycopg.errors.DeadlockDetected)
@app.errorhandler(psycopg.errors.SerializationFailure)
@app.errorhandler(psycopg.errors.LockNotAvailable)
def concurrent_database_error(error):
    return jsonify(error="Otro administrador está modificando estos datos. Recarga e inténtalo de nuevo."), 409


@app.errorhandler(psycopg.errors.CheckViolation)
def competition_integrity_error(error):
    return jsonify(error=integrity_message(error) or "No se pudieron guardar los cambios por una restricción de integridad."),409


@app.errorhandler(HTTPException)
def http_error(error):
    messages = {
        400: "La solicitud no es válida.",
        404: "No se encontró la página.",
        405: "La operación no está permitida.",
        413: "La solicitud es demasiado grande.",
        503: "El servicio no está disponible. Inténtalo de nuevo.",
    }
    return jsonify(error=messages.get(error.code, "No se pudo completar la solicitud.")), error.code


@app.errorhandler(Exception)
def internal_error(error):
    app.logger.error("Unexpected request failure (%s)", type(error).__name__)
    return jsonify(error="No se pudo completar la solicitud. Inténtalo de nuevo."), 500


def validate_sets(sets):
    """
    Validate a completed volleyball match.

    Sets 1-4: first to at least 25, win by 2.
    Set 5: first to at least 15, win by 2.
    A team must win 3 sets to win the match.
    """

    if not isinstance(sets, list) or not 3 <= len(sets) <= 5:
        return "Un partido finalizado debe contener entre 3 y 5 sets."

    wins1 = 0
    wins2 = 0
    validated_sets = []

    for index, item in enumerate(sets):
        if not isinstance(item, dict):
            return "Cada set debe incluir los puntos de ambos equipos."

        points1 = item.get("team1Points")
        points2 = item.get("team2Points")

        # Reject booleans, strings, negative scores, and missing scores.
        if (
            type(points1) is not int
            or type(points2) is not int
            or points1 < 0
            or points2 < 0
            or points1 > 2147483647
            or points2 > 2147483647
        ):
            return "Los puntos de cada set deben ser números enteros entre 0 y 2147483647."

        if "setNumber" in item and (type(item["setNumber"]) is not int or item["setNumber"] != index + 1):
            return "Los sets deben estar numerados consecutivamente desde el 1."

        if points1 == points2:
            return f"El set {index + 1} no puede terminar en empate."

        target = 15 if index == 4 else 25
        winner_points = max(points1, points2)
        loser_points = min(points1, points2)

        if winner_points < target:
            return (
                f"Set {index + 1}: el ganador debe anotar "
                f"al menos {target} puntos."
            )

        if winner_points - loser_points < 2:
            return (
                f"El set {index + 1} debe ganarse con una diferencia de al menos "
                "dos puntos."
            )

        if winner_points > target and winner_points - loser_points != 2:
            return f"El set {index + 1} debe terminar cuando se alcanza la puntuación ganadora."

        if points1 > points2:
            wins1 += 1
        else:
            wins2 += 1

        # No sets may be played after a team has won the match.
        if wins1 == 3 or wins2 == 3:
            if index != len(sets) - 1:
                return "No se pueden registrar más sets después de que un equipo gane 3 sets."

        validated_sets.append((index + 1, points1, points2))

    if wins1 != 3 and wins2 != 3:
        return "Un equipo debe ganar exactamente 3 sets."

    # A fifth set is required only when the first four sets split 2-2.
    if len(sets) == 5 and (wins1, wins2) not in ((3, 2), (2, 3)):
        return "Un quinto set solo es válido cuando el partido termina 3-2."

    if len(sets) == 4 and (wins1, wins2) not in ((3, 1), (1, 3)):
        return "Un partido de cuatro sets debe terminar 3-1."

    if len(sets) == 3 and (wins1, wins2) not in ((3, 0), (0, 3)):
        return "Un partido de tres sets debe terminar 3-0."

    return validated_sets


@app.route("/api/jornadas", methods=["GET"])
def get_jornadas(tournament_id=None):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            scope = requested_tournament(conn,tournament_id)
            cur.execute("""
                SELECT
                    j.id,
                    j.number,
                    m.id,
                    m.match_time,
                    t1.name AS team1,
                    t2.name AS team2,
                    m.status,
                    m.scheduled_at,m.team1_id,m.team2_id,t1.logo_path,t2.logo_path
                FROM jornadas AS j
                LEFT JOIN matches AS m
                    ON m.jornada_id = j.id
                LEFT JOIN tournament_team_identities AS t1
                    ON t1.id = m.team1_id AND t1.tournament_id=j.tournament_id
                LEFT JOIN tournament_team_identities AS t2
                    ON t2.id = m.team2_id AND t2.tournament_id=j.tournament_id
                WHERE j.tournament_id = COALESCE(%s,(SELECT id FROM tournaments WHERE is_public=TRUE))
                ORDER BY j.number, m.scheduled_at NULLS LAST, m.match_time, m.id LIMIT 50001
            """,(scope,))
            rows = checked_rows(cur.fetchall())

            cur.execute("""
                SELECT
                    ms.match_id, ms.set_number, ms.team1_points, ms.team2_points
                FROM match_sets ms JOIN matches m ON m.id=ms.match_id JOIN jornadas j ON j.id=m.jornada_id
                WHERE j.tournament_id=COALESCE(%s,(SELECT id FROM tournaments WHERE is_public=TRUE))
                ORDER BY ms.match_id, ms.set_number LIMIT 50001
            """,(scope,))
            set_rows = checked_rows(cur.fetchall())

    sets_by_match = {}

    for match_id, set_number, points1, points2 in set_rows:
        sets_by_match.setdefault(match_id, []).append({
            "setNumber": set_number,
            "team1Points": points1,
            "team2Points": points2,
        })

    jornadas_by_id = {}

    for (
        jornada_id,
        jornada_number,
        match_id,
        match_time,
        team1,
        team2,
        status,
        scheduled_at,
        team1_id,team2_id,logo1,logo2,
    ) in rows:
        if jornada_id not in jornadas_by_id:
            jornadas_by_id[jornada_id] = {
                "id": jornada_id,
                "number": jornada_number,
                "games": [],
            }

        if match_id is None:
            continue

        game = {
            "id": match_id,
            "time": scheduled_at.astimezone(HAVANA).strftime("%H:%M") if scheduled_at else (match_time.strftime("%H:%M") if match_time else "Horario por confirmar"),
            "team1": team1,
            "team2": team2,
            "team1Id":team1_id,"team2Id":team2_id,"team1Logo":logo1 or "","team2Logo":logo2 or "",
            "status": status or "",
            **schedule_fields(scheduled_at),
        }

        match_sets = sets_by_match.get(match_id, [])

        if match_sets:
            game["results"] = {"sets": match_sets}

        jornadas_by_id[jornada_id]["games"].append(game)

    return jsonify(list(jornadas_by_id.values()))


@app.route("/api/standings", methods=["GET"])
def get_standings(tournament_id=None):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            scope = requested_tournament(conn,tournament_id)
            cur.execute("""
                SELECT t.id, t.name, t.logo_path FROM tournament_team_identities t
                WHERE t.tournament_id=COALESCE(%s,(SELECT id FROM tournaments WHERE is_public=TRUE))
                ORDER BY t.id LIMIT 50001
            """,(scope,))
            teams = checked_rows(cur.fetchall())

            cur.execute("""
                SELECT
                    m.id,
                    m.team1_id,
                    m.team2_id,
                    ms.set_number,
                    ms.team1_points,
                    ms.team2_points
                FROM matches AS m
                JOIN match_sets AS ms
                    ON ms.match_id = m.id
                JOIN jornadas j ON j.id=m.jornada_id
                WHERE m.status = 'finished' AND j.tournament_id=COALESCE(%s,(SELECT id FROM tournaments WHERE is_public=TRUE))
                ORDER BY m.id, ms.set_number LIMIT 50001
            """,(scope,))
            rows = checked_rows(cur.fetchall())

    standings = {
        team_id: {
            "team": name,
            "teamId":team_id,"logo":logo or "",
            "wins": 0,
            "losses": 0,
            "setsWon": 0,
            "setsLost": 0,
        }
        for team_id, name, logo in teams
    }

    matches_by_id = {}

    for match_id, team1_id, team2_id, set_number, points1, points2 in rows:
        if match_id not in matches_by_id:
            matches_by_id[match_id] = {
                "team1_id": team1_id,
                "team2_id": team2_id,
                "sets": [],
            }

        matches_by_id[match_id]["sets"].append(
            (set_number, points1, points2)
        )

    for match in matches_by_id.values():
        team1_id = match["team1_id"]
        team2_id = match["team2_id"]
        sets = match["sets"]

        if (team1_id not in standings or team2_id not in standings
                or team1_id == team2_id
                or [number for number, _, _ in sets] != list(range(1, len(sets) + 1))
                or isinstance(validate_sets([
                    {"team1Points": p1, "team2Points": p2}
                    for _, p1, p2 in sets
                ]), str)):
            continue

        sets1 = sum(1 for _, p1, p2 in sets if p1 > p2)
        sets2 = sum(1 for _, p1, p2 in sets if p2 > p1)

        standings[team1_id]["setsWon"] += sets1
        standings[team1_id]["setsLost"] += sets2
        standings[team2_id]["setsWon"] += sets2
        standings[team2_id]["setsLost"] += sets1

        if sets1 > sets2:
            standings[team1_id]["wins"] += 1
            standings[team2_id]["losses"] += 1
        elif sets2 > sets1:
            standings[team2_id]["wins"] += 1
            standings[team1_id]["losses"] += 1

    result = sorted(
        standings.values(),
        key=lambda team: (
            -team["wins"],
            -(team["setsWon"] - team["setsLost"]),
            -team["setsWon"],
            team["team"].lower(),
        ),
    )

    return jsonify(result)


@app.route(
    "/api/admin/matches/<int:match_id>/result",
    methods=["PUT"],
)
def save_match_result(match_id):
    data = request.get_json(silent=True)

    if not isinstance(data, dict) or "sets" not in data:
        return jsonify({
            "error": "Envía los resultados con una lista de sets."
        }), 400

    validated_sets = validate_sets(data["sets"])

    if isinstance(validated_sets, str):
        return jsonify({"error": validated_sets}), 400

    # The transaction makes replacing the old result atomic.
    # If any database operation fails, the changes are rolled back.
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                scope = management_tournament(conn)
                cur.execute("""
                    SELECT m.id, m.team1_id, m.team2_id, j.tournament_id
                    FROM matches m JOIN jornadas j ON j.id=m.jornada_id
                    WHERE m.id = %s AND j.tournament_id=%s
                    FOR UPDATE OF m
                """, (match_id,scope))

                match = cur.fetchone()

                if match is None:
                    return jsonify({
                        "error": f"No se encontró el partido {match_id}."
                    }), 404
                require_open(conn,match[3])

                # Delete the previous scores before inserting corrections.
                cur.execute("""
                    DELETE FROM match_sets
                    WHERE match_id = %s
                """, (match_id,))

                cur.executemany("""
                    INSERT INTO match_sets (
                        match_id,
                        set_number,
                        team1_points,
                        team2_points
                    )
                    VALUES (%s, %s, %s, %s)
                """, [
                    (match_id, number, points1, points2)
                    for number, points1, points2 in validated_sets
                ])

                cur.execute("""
                    UPDATE matches
                    SET status = 'finished'
                    WHERE id = %s
                """, (match_id,))

    except (psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure, psycopg.errors.LockNotAvailable):
        return jsonify(error="Otro administrador está modificando estos datos. Recarga e inténtalo de nuevo."), 409
    except psycopg.errors.CheckViolation as error:
        if integrity_message(error):
            return jsonify(error=integrity_message(error)),409
        app.logger.error("Database integrity error while saving match result")
        return jsonify(error="No se pudo guardar el resultado. No se guardaron cambios."),500
    except psycopg.OperationalError:
        return jsonify(error="El servicio no está disponible. No se guardaron cambios. Inténtalo de nuevo."),503
    except psycopg.Error as error:
        app.logger.error("Database result update failed (%s)", type(error).__name__)
        return jsonify({
            "error": "No se pudo guardar el resultado. No se guardaron cambios."
        }), 500

    return jsonify({
        "message": "Resultado guardado correctamente.",
        "matchId": match_id,
        "status": "finished",
        "sets": [
            {
                "setNumber": number,
                "team1Points": points1,
                "team2Points": points2,
            }
            for number, points1, points2 in validated_sets
        ],
    }), 200


@app.route("/api/admin/stats", methods=["GET"])
def get_admin_stats():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            scope = requested_tournament(conn)
            cur.execute("SELECT COUNT(*) FROM tournament_teams WHERE tournament_id=COALESCE(%s,(SELECT id FROM tournaments WHERE is_public=TRUE))",(scope,))
            total_teams = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM jornadas WHERE tournament_id=COALESCE(%s,(SELECT id FROM tournaments WHERE is_public=TRUE))",(scope,))
            total_jornadas = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM matches m JOIN jornadas j ON j.id=m.jornada_id WHERE j.tournament_id=COALESCE(%s,(SELECT id FROM tournaments WHERE is_public=TRUE))",(scope,))
            total_matches = cur.fetchone()[0]

    return jsonify({
        "teams": total_teams,
        "jornadas": total_jornadas,
        "matches": total_matches,
    })


install_competitions(app, lambda: get_db_connection(), validate_sets)
app.add_url_rule('/api/tournaments/<int:tournament_id>/jornadas','tournament_public_jornadas',get_jornadas)
app.add_url_rule('/api/tournaments/<int:tournament_id>/standings','tournament_public_standings',get_standings)

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "3000")),
            debug=not production and os.environ.get("FLASK_DEBUG") == "1")
