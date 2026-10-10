from datetime import datetime, timezone
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import click
from flask import jsonify, request
import psycopg
from validation import positive_integer
from competitions import requested_tournament, management_tournament, require_open, integrity_message
from werkzeug.exceptions import BadRequest

HAVANA = ZoneInfo("America/Havana")
DEFAULT_DURATION_MINUTES = 120


def parse_start(date, time):
    if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("Introduce una fecha válida.")
    if not isinstance(time, str) or not re.fullmatch(r"\d{2}:\d{2}", time):
        raise ValueError("Introduce una hora válida en formato de 24 horas.")
    try:
        local = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    except ValueError as error:
        raise ValueError("La fecha o la hora no es válida.") from error
    # Round-trip both DST folds: reject nonexistent or ambiguous local times.
    candidates = set()
    for fold in (0, 1):
        try:
            utc = local.replace(tzinfo=HAVANA, fold=fold).astimezone(timezone.utc)
        except (OverflowError, ValueError) as error:
            raise ValueError("La fecha está fuera del intervalo permitido.") from error
        if utc.astimezone(HAVANA).replace(tzinfo=None) == local:
            candidates.add(utc)
    if len(candidates) != 1:
        raise ValueError("La hora no existe o es ambigua por el cambio de horario en Cuba. Elige otra hora.")
    return candidates.pop()


def schedule_fields(start):
    if not start:
        return {"startsAt": None, "date": None}
    local = start.astimezone(HAVANA)
    return {"startsAt": start.astimezone(timezone.utc).isoformat(), "date": local.date().isoformat()}


def install_scheduling(app, connect):
    def payload():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("Envía una solicitud válida.")
        return data

    @app.get("/api/admin/jornadas")
    def admin_jornadas():
        with connect() as conn:
            scope = requested_tournament(conn)
            jornadas = conn.execute("SELECT id, number FROM jornadas WHERE tournament_id=COALESCE(%s,(SELECT id FROM tournaments WHERE is_public=TRUE)) ORDER BY number, id",(scope,)).fetchall()
            matches = conn.execute(
                "SELECT m.id, m.jornada_id, m.team1_id, m.team2_id, m.match_time, m.scheduled_at, m.status, "
                "EXISTS (SELECT 1 FROM match_sets s WHERE s.match_id = m.id), t1.name, t2.name, m.duration_minutes, m.best_of "
                "FROM matches m JOIN jornadas j ON j.id=m.jornada_id "
                "JOIN tournament_team_identities t1 ON t1.id = m.team1_id AND t1.tournament_id=j.tournament_id "
                "JOIN tournament_team_identities t2 ON t2.id = m.team2_id AND t2.tournament_id=j.tournament_id "
                "WHERE j.tournament_id=COALESCE(%s,(SELECT id FROM tournaments WHERE is_public=TRUE)) "
                "ORDER BY m.scheduled_at NULLS LAST, m.match_time, m.id"
            ,(scope,)).fetchall()
        grouped = {row[0]: {"id": row[0], "number": row[1], "games": []} for row in jornadas}
        for id, jornada, team1, team2, time, start, status, scores, name1, name2, duration, best_of in matches:
            grouped[jornada]["games"].append({
                "id": id, "team1Id": team1, "team2Id": team2, "team1": name1, "team2": name2,
                "time": start.astimezone(HAVANA).strftime("%H:%M") if start else time.strftime("%H:%M"),
                "status": "finished" if status == "finished" else "scheduled", "hasResults": scores,
                **schedule_fields(start),
                "durationMinutes": duration,
                "bestOf": best_of,
            })
        return jsonify(list(grouped.values()))

    def save_jornada(jornada_id=None):
        try:
            data = payload()
            number = positive_integer(data.get("number"), "El número de jornada")
            with connect() as conn:
                scope = management_tournament(conn)
                require_open(conn,scope)
                if "tournamentId" in data and positive_integer(data["tournamentId"],"El torneo")!=scope:
                    raise BadRequest("El torneo indicado no coincide con el seleccionado.")
                if jornada_id is None:
                    row = conn.execute("INSERT INTO jornadas (number,tournament_id) VALUES (%s,%s) RETURNING id, number", (number,scope)).fetchone()
                else:
                    row = conn.execute("UPDATE jornadas SET number = %s WHERE id = %s AND tournament_id=%s RETURNING id, number", (number, jornada_id,scope)).fetchone()
                    if not row:
                        return jsonify(error="No se encontró la jornada."), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except psycopg.errors.UniqueViolation:
            return jsonify(error="Ya existe una jornada con ese número."), 409
        return jsonify(message="Jornada guardada correctamente.", jornada={"id": row[0], "number": row[1]}), 201 if jornada_id is None else 200

    app.add_url_rule("/api/admin/jornadas", "create_jornada", save_jornada, methods=["POST"])
    app.add_url_rule("/api/admin/jornadas/<int:jornada_id>", "update_jornada", save_jornada, methods=["PUT"])

    @app.delete("/api/admin/jornadas/<int:jornada_id>")
    def delete_jornada(jornada_id):
        try:
            with connect() as conn:
                scope = management_tournament(conn)
                require_open(conn,scope)
                if not conn.execute("SELECT id FROM jornadas WHERE id = %s AND tournament_id=%s FOR UPDATE", (jornada_id,scope)).fetchone():
                    return jsonify(error="No se encontró la jornada."), 404
                if conn.execute("SELECT EXISTS (SELECT 1 FROM matches WHERE jornada_id = %s)", (jornada_id,)).fetchone()[0]:
                    return jsonify(error="No se puede eliminar una jornada con partidos. Se conserva su historial."), 409
                conn.execute("DELETE FROM jornadas WHERE id = %s", (jornada_id,))
        except psycopg.errors.ForeignKeyViolation:
            return jsonify(error="No se puede eliminar una jornada con registros asociados."), 409
        return jsonify(message="Jornada eliminada correctamente.")

    def save_match(match_id=None, jornada_id=None):
        try:
            data = payload()
            team1 = positive_integer(data.get("team1Id"), "El primer equipo")
            team2 = positive_integer(data.get("team2Id"), "El segundo equipo")
            if team1 == team2:
                raise ValueError("Un equipo no puede jugar contra sí mismo.")
            start = parse_start(data.get("date"), data.get("time"))
            local_time = start.astimezone(HAVANA).time().replace(tzinfo=None)
            with connect() as conn:
                conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                scope = management_tournament(conn)
                competition = require_open(conn,scope)
                if "tournamentId" in data and positive_integer(data["tournamentId"],"El torneo")!=scope:
                    raise ValueError("El torneo indicado no coincide con el seleccionado.")
                if (competition[2] and start.astimezone(HAVANA).date()<competition[2]) or (competition[3] and start.astimezone(HAVANA).date()>competition[3]):
                    raise ValueError("La fecha del partido debe estar dentro de las fechas del torneo.")
                existing = None
                if match_id is not None:
                    existing = conn.execute(
                        "SELECT m.jornada_id, m.team1_id, m.team2_id, m.status, m.duration_minutes, m.best_of FROM matches m JOIN jornadas j ON j.id=m.jornada_id WHERE m.id = %s AND j.tournament_id=%s FOR UPDATE OF m", (match_id,scope),
                    ).fetchone()
                    if not existing:
                        return jsonify(error="No se encontró el partido."), 404
                    jornada_id = existing[0]
                    recorded = existing[3] == "finished" or conn.execute(
                        "SELECT EXISTS (SELECT 1 FROM match_sets WHERE match_id = %s)", (match_id,),
                    ).fetchone()[0]
                    if recorded and ((team1, team2) != existing[1:3] or data.get("bestOf", existing[5]) != existing[5]):
                        return jsonify(error="No se pueden cambiar los equipos ni el formato de un partido con resultados registrados."), 409
                best_of = data.get("bestOf", existing[5] if existing else 3)
                if type(best_of) is not int or best_of not in (3, 5):
                    raise ValueError("El formato debe ser al mejor de 3 o de 5 sets.")
                if "jornadaId" in data and positive_integer(data["jornadaId"], "La jornada") != jornada_id:
                    raise ValueError("La jornada indicada no coincide con la del partido.")
                duration = positive_integer(data.get("durationMinutes", existing[4] if existing else DEFAULT_DURATION_MINUTES), "La duración")
                if duration > 1440:
                    raise ValueError("La duración del partido debe ser de entre 1 y 1440 minutos.")
                # Serialize writers sharing a team, using a stable lock order.
                if not conn.execute("SELECT id FROM jornadas WHERE id = %s AND tournament_id=%s FOR KEY SHARE", (jornada_id,scope)).fetchone():
                    return jsonify(error="No se encontró la jornada."), 404
                found = conn.execute("SELECT id FROM teams WHERE id IN (%s, %s) ORDER BY id FOR UPDATE", (team1, team2)).fetchall()
                if len(found) != 2:
                    raise ValueError("Selecciona dos equipos existentes.")
                if conn.execute("SELECT COUNT(*) FROM tournament_teams WHERE tournament_id=%s AND team_id IN(%s,%s)",(scope,team1,team2)).fetchone()[0]!=2:
                    raise ValueError("Ambos equipos deben estar inscritos en el torneo.")
                # Include time-only historical fixtures in duplicate detection.
                if conn.execute(
                    "SELECT EXISTS (SELECT 1 FROM matches WHERE jornada_id = %s "
                    "AND LEAST(team1_id, team2_id) = %s AND GREATEST(team1_id, team2_id) = %s "
                    "AND (scheduled_at = %s OR (scheduled_at IS NULL AND match_time = %s)) "
                    "AND id <> %s)",
                    (jornada_id, min(team1, team2), max(team1, team2), start, local_time, match_id or 0),
                ).fetchone()[0]:
                    return jsonify(error="Ya existe este partido en la jornada para ese horario."), 409
                if match_id is None:
                    row = conn.execute(
                        "INSERT INTO matches (jornada_id, team1_id, team2_id, match_time, scheduled_at, status, duration_minutes, best_of) "
                        "VALUES (%s, %s, %s, %s, %s, 'scheduled', %s, %s) RETURNING id",
                        (jornada_id, team1, team2, local_time, start, duration, best_of),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "UPDATE matches SET team1_id = %s, team2_id = %s, match_time = %s, scheduled_at = %s, duration_minutes = %s, best_of = %s "
                        "WHERE id = %s RETURNING id", (team1, team2, local_time, start, duration, best_of, match_id),
                    ).fetchone()
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except psycopg.errors.UniqueViolation:
            return jsonify(error="Ya existe este partido en la jornada para ese horario."), 409
        except psycopg.errors.ExclusionViolation:
            return jsonify(error="Uno de los equipos ya tiene un partido que se solapa con este horario."), 409
        except psycopg.errors.CheckViolation as error:
            return jsonify(error=integrity_message(error) or "No se pueden modificar los equipos, la jornada o el estado de un partido con resultados registrados."), 409
        except psycopg.errors.ForeignKeyViolation:
            return jsonify(error="La jornada o alguno de los equipos ya no está disponible."), 409
        return jsonify(message="Partido guardado correctamente.", matchId=row[0]), 201 if match_id is None else 200

    app.add_url_rule("/api/admin/jornadas/<int:jornada_id>/matches", "create_scheduled_match", save_match, methods=["POST"])
    app.add_url_rule("/api/admin/matches/<int:match_id>", "update_scheduled_match", save_match, methods=["PUT"])

    @app.delete("/api/admin/matches/<int:match_id>")
    def delete_scheduled_match(match_id):
        try:
            with connect() as conn:
                scope = management_tournament(conn)
                require_open(conn,scope)
                match = conn.execute("SELECT m.status FROM matches m JOIN jornadas j ON j.id=m.jornada_id WHERE m.id = %s AND j.tournament_id=%s FOR UPDATE OF m", (match_id,scope)).fetchone()
                if not match:
                    return jsonify(error="No se encontró el partido."), 404
                scores = conn.execute("SELECT EXISTS (SELECT 1 FROM match_sets WHERE match_id = %s)", (match_id,)).fetchone()[0]
                if match[0] == "finished" or scores:
                    return jsonify(error="No se puede eliminar un partido con resultados registrados. Se conserva su historial."), 409
                conn.execute("DELETE FROM matches WHERE id = %s", (match_id,))
        except psycopg.errors.ForeignKeyViolation:
            return jsonify(error="No se puede eliminar un partido con registros asociados."), 409
        except psycopg.errors.CheckViolation as error:
            return jsonify(error=integrity_message(error) or "No se puede eliminar un partido con resultados registrados. Se conserva su historial."), 409
        return jsonify(message="Partido eliminado correctamente.")

    @app.cli.command("init-scheduling")
    def init_scheduling():
        """Prepara jornadas y horarios sin cambiar los registros históricos."""
        try:
            with connect() as conn:
                version = '005_competitions.sql' if conn.execute("SELECT to_regclass('tournaments') IS NOT NULL").fetchone()[0] else '003_scheduling.sql'
                conn.execute((Path(__file__).parent / "migrations" / version).read_text(encoding="utf-8"))
                if version=='005_competitions.sql' and conn.execute("SELECT EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid='tournament_teams'::regclass AND attname='snapshot_created_at')").fetchone()[0]:
                    from snapshots import apply_snapshots
                    apply_snapshots(conn)
        except psycopg.errors.UniqueViolation as error:
            raise click.ClickException("Hay jornadas con números duplicados. Corrígelos antes de migrar; no se ha eliminado ningún dato.") from error
        click.echo("Gestión de jornadas preparada. Se conservó el historial de la liga.")

    @app.cli.command("init-business-rules")
    def init_business_rules():
        """Añade reglas de integridad sin modificar el historial."""
        with connect() as conn:
            version = '005_competitions.sql' if conn.execute("SELECT to_regclass('tournaments') IS NOT NULL").fetchone()[0] else '004_business_rules.sql'
            conn.execute((Path(__file__).parent / "migrations" / version).read_text(encoding="utf-8"))
            if version=='005_competitions.sql' and conn.execute("SELECT EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid='tournament_teams'::regclass AND attname='snapshot_created_at')").fetchone()[0]:
                from snapshots import apply_snapshots
                apply_snapshots(conn)
        click.echo("Reglas de integridad preparadas. Se conservó el historial de la liga.")

    @app.cli.command("init-match-formats")
    def init_match_formats():
        """Conserva los formatos anteriores y prepara partidos al mejor de tres."""
        with connect() as conn:
            conn.execute((Path(__file__).parent / "migrations/007_match_formats.sql").read_text(encoding="utf-8"))
        click.echo("Formatos preparados. Los partidos existentes conservan su formato.")
