from datetime import date
from pathlib import Path
import re

import click
from flask import jsonify, request
import psycopg
from werkzeug.exceptions import BadRequest, Conflict, NotFound
from validation import positive_integer, validate_name
from reliability import catalog_page
from snapshots import prepare_logos, apply_snapshots

TRANSITIONS = {"planned": {"planned","active","completed","archived"}, "active": {"active","completed","archived"}, "completed": {"completed","archived"}, "archived": {"archived"}}
COLUMNS = "id, name, start_date, end_date, status"


def requested_tournament(conn, tournament_id=None):
    raw = tournament_id if tournament_id is not None else request.args.get("tournament_id")
    if raw is None:
        return None
    try:
        id = positive_integer(raw, "El torneo")
    except ValueError as error:
        raise BadRequest(str(error)) from error
    if not conn.execute("SELECT id FROM tournaments WHERE id = %s", (id,)).fetchone():
        raise NotFound("No se encontró el torneo.")
    return id


def management_tournament(conn, supplied=None):
    id = requested_tournament(conn, supplied)
    if id is None:
        row = conn.execute("SELECT id FROM tournaments WHERE is_public = TRUE").fetchone()
        if not row:
            raise Conflict("Selecciona un torneo; no hay un torneo público activo.")
        id = row[0]
    return id


def require_open(conn, tournament_id):
    row = conn.execute(
        "SELECT t.id, t.status, t.start_date, t.end_date, s.status FROM tournaments t "
        "JOIN seasons s ON s.id=t.season_id WHERE t.id=%s FOR SHARE OF t,s", (tournament_id,),
    ).fetchone()
    if not row:
        raise NotFound("No se encontró el torneo.")
    if row[1] in {"completed","archived"} or row[4] in {"completed","archived"}:
        raise Conflict("La temporada o el torneo está cerrado. Su historial no se puede modificar.")
    return row


def integrity_message(error):
    return {"competition_closed":"La competición está cerrada. Su historial no se puede modificar.",
            "snapshot_immutable":"La identidad histórica del equipo no se puede modificar.",
            "snapshot_logo":"Preserva los logotipos locales antes de cerrar la competición.",
            "competition_ownership":"No se puede cambiar la asociación histórica de la competición.",
            "competition_roster":"Ambos equipos deben estar inscritos en el torneo.",
            "competition_dates":"Las fechas deben estar dentro de las fechas de la competición.",
            "roster_history":"No se puede retirar un equipo que tiene partidos en este torneo."}.get(error.diag.constraint_name)


def competition_json(row, tournament=False):
    data = dict(zip(("id","name","startDate","endDate","status"), row[:5]))
    for key in ("startDate","endDate"):
        data[key] = data[key].isoformat() if data[key] else None
    if tournament:
        data.update(seasonId=row[5], isPublic=row[6])
    return data


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest("Envía una solicitud válida.")
    return data


def details(data, existing=None):
    previous = competition_json(existing) if existing else {}
    try:
        name = validate_name(data.get("name", previous.get("name")))
    except ValueError as error:
        raise BadRequest("El nombre es obligatorio, debe tener hasta 100 caracteres y no contener caracteres de control.") from error
    dates = []
    for field in ("startDate","endDate"):
        value = data.get(field, previous.get(field))
        if value is None:
            dates.append(None)
            continue
        try:
            if not isinstance(value,str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}",value):
                raise ValueError()
            dates.append(date.fromisoformat(value))
        except ValueError as error:
            raise BadRequest("Introduce fechas válidas con formato AAAA-MM-DD.") from error
    if dates[0] and dates[1] and dates[0] > dates[1]:
        raise BadRequest("La fecha final no puede ser anterior a la inicial.")
    status = data.get("status", previous.get("status","planned"))
    if not isinstance(status,str) or status not in TRANSITIONS:
        raise BadRequest("El estado de la competición no es válido.")
    if status not in TRANSITIONS[previous.get("status","planned")]:
        raise Conflict("No se puede reabrir una competición completada o archivada.")
    if existing and existing[4] in {"completed","archived"} and (name, *dates) != (existing[1], existing[2], existing[3]):
        raise Conflict("Los detalles de una competición cerrada no se pueden modificar.")
    return name, *dates, status


def activation_lock(conn):
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('voli_public_tournament',0))")


def install_competitions(app, connect, validate_sets):
    @app.errorhandler(BadRequest)
    @app.errorhandler(Conflict)
    @app.errorhandler(NotFound)
    def competition_http_error(error):
        # Werkzeug's default descriptions are English; expose only our Spanish messages.
        message = error.description if error.description != type(error).description else {400:"La solicitud no es válida.",404:"No se encontró la página.",409:"No se pudieron guardar los cambios."}[error.code]
        return jsonify(error=message), error.code

    def list_seasons():
        limit,offset = catalog_page()
        with connect() as conn:
            rows = conn.execute(f"SELECT {COLUMNS} FROM seasons ORDER BY id LIMIT %s OFFSET %s",(limit,offset)).fetchall()
        return jsonify([competition_json(row) for row in rows])

    app.add_url_rule("/api/admin/seasons", "list_seasons", list_seasons)
    app.add_url_rule("/api/seasons", "list_public_seasons", list_seasons)

    def list_tournaments(season_id=None):
        limit,offset = catalog_page()
        with connect() as conn:
            if season_id is not None and not conn.execute("SELECT id FROM seasons WHERE id=%s",(season_id,)).fetchone():
                raise NotFound("No se encontró la temporada.")
            rows = conn.execute(f"SELECT {COLUMNS},season_id,is_public FROM tournaments WHERE (%s::integer IS NULL OR season_id=%s) ORDER BY id LIMIT %s OFFSET %s",(season_id,season_id,limit,offset)).fetchall()
        return jsonify([competition_json(row,True) for row in rows])

    app.add_url_rule("/api/admin/tournaments","list_admin_tournaments",list_tournaments)
    app.add_url_rule("/api/admin/seasons/<int:season_id>/tournaments","season_tournaments",list_tournaments)
    app.add_url_rule("/api/tournaments","list_public_tournaments",list_tournaments)

    @app.get("/api/tournaments/active")
    def active_tournament():
        with connect() as conn:
            row = conn.execute(f"SELECT {COLUMNS},season_id,is_public FROM tournaments WHERE is_public=TRUE").fetchone()
        if not row:
            raise NotFound("No hay un torneo público activo.")
        return jsonify(competition_json(row,True))

    @app.get("/api/tournaments/<int:tournament_id>")
    def get_tournament(tournament_id):
        with connect() as conn:
            row = conn.execute(f"SELECT {COLUMNS},season_id,is_public FROM tournaments WHERE id=%s",(tournament_id,)).fetchone()
        if not row:
            raise NotFound("No se encontró el torneo.")
        return jsonify(competition_json(row,True))

    def save_season(season_id=None):
        data = payload()
        try:
            with connect() as conn:
                activation_lock(conn)
                old = None
                if season_id is not None:
                    old = conn.execute(f"SELECT {COLUMNS} FROM seasons WHERE id=%s FOR UPDATE",(season_id,)).fetchone()
                    if not old:
                        raise NotFound("No se encontró la temporada.")
                name, start, end, status = details(data,old)
                if old:
                    children = conn.execute("SELECT start_date,end_date,status FROM tournaments WHERE season_id=%s",(season_id,)).fetchall()
                    if status in {"completed","archived"} and any(c[2] not in {"completed","archived"} for c in children):
                        raise Conflict("Cierra los torneos de la temporada antes de cerrarla.")
                    if any((start and (c[0] is None or c[0]<start)) or (end and (c[1] is None or c[1]>end)) for c in children):
                        raise Conflict("Las fechas de la temporada deben incluir las de sus torneos.")
                    row = conn.execute(f"UPDATE seasons SET name=%s,start_date=%s,end_date=%s,status=%s WHERE id=%s RETURNING {COLUMNS}",(name,start,end,status,season_id)).fetchone()
                else:
                    row = conn.execute(f"INSERT INTO seasons(name,start_date,end_date,status) VALUES(%s,%s,%s,%s) RETURNING {COLUMNS}",(name,start,end,status)).fetchone()
        except psycopg.errors.UniqueViolation:
            raise Conflict("Ya existe una temporada con ese nombre.")
        return jsonify(message="Temporada guardada correctamente.",season=competition_json(row)), 200 if old else 201

    app.add_url_rule("/api/admin/seasons","create_season",save_season,methods=["POST"])
    app.add_url_rule("/api/admin/seasons/<int:season_id>","update_season",save_season,methods=["PUT"])

    def save_tournament(tournament_id=None,season_id=None):
        data = payload()
        try:
            with connect() as conn:
                activation_lock(conn)
                old = None
                if tournament_id is not None:
                    old = conn.execute(f"SELECT {COLUMNS},season_id,is_public FROM tournaments WHERE id=%s FOR UPDATE",(tournament_id,)).fetchone()
                    if not old:
                        raise NotFound("No se encontró el torneo.")
                    season_id = old[5]
                try:
                    if season_id is None:
                        season_id = positive_integer(data.get("seasonId"),"La temporada")
                    if "seasonId" in data and positive_integer(data["seasonId"],"La temporada") != season_id:
                        raise Conflict("El torneo debe conservar su temporada.")
                except ValueError as error:
                    raise BadRequest(str(error)) from error
                parent = conn.execute("SELECT start_date,end_date,status FROM seasons WHERE id=%s FOR SHARE",(season_id,)).fetchone()
                if not parent:
                    raise NotFound("No se encontró la temporada.")
                if parent[2] in {"completed","archived"} and not (old and old[4]=="completed" and data.get("status")=="archived"):
                    raise Conflict("La temporada está cerrada.")
                name, start, end, status = details(data,old)
                if (parent[0] and (start is None or start<parent[0])) or (parent[1] and (end is None or end>parent[1])):
                    raise BadRequest("Las fechas del torneo deben estar dentro de la temporada.")
                if old:
                    matches = conn.execute("SELECT m.status,m.id,m.scheduled_at FROM matches m JOIN jornadas j ON j.id=m.jornada_id WHERE j.tournament_id=%s",(tournament_id,)).fetchall()
                    from scheduling import HAVANA
                    if any(m[2] and ((start and m[2].astimezone(HAVANA).date()<start) or (end and m[2].astimezone(HAVANA).date()>end)) for m in matches):
                        raise Conflict("Las fechas del torneo deben incluir sus partidos.")
                    if status=="completed" and old[4] not in {"completed","archived"}:
                        for state,match_id,_ in matches:
                            scores = conn.execute("SELECT set_number,team1_points,team2_points FROM match_sets WHERE match_id=%s ORDER BY set_number",(match_id,)).fetchall()
                            if state!="finished" or isinstance(validate_sets([{"setNumber":n,"team1Points":p1,"team2Points":p2} for n,p1,p2 in scores]),str):
                                raise Conflict("Completa todos los partidos con resultados válidos antes de completar el torneo.")
                    if status in {"completed","archived"} and old[4] not in {"completed","archived"}:
                        prepare_logos(conn,tournament_id)
                    row = conn.execute(f"UPDATE tournaments SET name=%s,start_date=%s,end_date=%s,status=%s,is_public=CASE WHEN %s IN ('completed','archived') THEN FALSE ELSE is_public END WHERE id=%s RETURNING {COLUMNS},season_id,is_public",(name,start,end,status,status,tournament_id)).fetchone()
                else:
                    row = conn.execute(f"INSERT INTO tournaments(season_id,name,start_date,end_date,status) VALUES(%s,%s,%s,%s,%s) RETURNING {COLUMNS},season_id,is_public",(season_id,name,start,end,status)).fetchone()
        except psycopg.errors.UniqueViolation:
            raise Conflict("Ya existe un torneo con ese nombre en la temporada.")
        return jsonify(message="Torneo guardado correctamente.",tournament=competition_json(row,True)), 200 if old else 201

    app.add_url_rule("/api/admin/tournaments","create_tournament",save_tournament,methods=["POST"])
    app.add_url_rule("/api/admin/seasons/<int:season_id>/tournaments","create_season_tournament",save_tournament,methods=["POST"])
    app.add_url_rule("/api/admin/tournaments/<int:tournament_id>","update_tournament",save_tournament,methods=["PUT"])

    @app.post("/api/admin/tournaments/<int:tournament_id>/activate")
    def activate_tournament(tournament_id):
        with connect() as conn:
            activation_lock(conn)
            require_open(conn,tournament_id)
            conn.execute("UPDATE tournaments SET is_public=FALSE WHERE is_public=TRUE")
            row = conn.execute(f"UPDATE tournaments SET is_public=TRUE,status='active' WHERE id=%s RETURNING {COLUMNS},season_id,is_public",(tournament_id,)).fetchone()
        return jsonify(message="Torneo público activo actualizado.",tournament=competition_json(row,True))

    @app.get("/api/admin/tournaments/<int:tournament_id>/teams")
    def registered_teams(tournament_id):
        with connect() as conn:
            requested_tournament(conn,tournament_id)
            rows = conn.execute("SELECT id,name,logo_path FROM tournament_team_identities WHERE tournament_id=%s ORDER BY id",(tournament_id,)).fetchall()
        return jsonify([{"id":id,"name":name,"logo":logo or ""} for id,name,logo in rows])

    @app.post("/api/admin/tournaments/<int:tournament_id>/teams")
    def register_team(tournament_id):
        try:
            team = positive_integer(payload().get("teamId"),"El equipo")
            with connect() as conn:
                require_open(conn,tournament_id)
                if not conn.execute("SELECT id FROM teams WHERE id=%s FOR KEY SHARE",(team,)).fetchone():
                    raise NotFound("No se encontró el equipo.")
                conn.execute("INSERT INTO tournament_teams(tournament_id,team_id) VALUES(%s,%s)",(tournament_id,team))
        except ValueError as error:
            raise BadRequest(str(error)) from error
        except psycopg.errors.UniqueViolation:
            raise Conflict("El equipo ya está inscrito en este torneo.")
        return jsonify(message="Equipo inscrito correctamente."),201

    @app.delete("/api/admin/tournaments/<int:tournament_id>/teams/<int:team_id>")
    def unregister_team(tournament_id,team_id):
        try:
            with connect() as conn:
                require_open(conn,tournament_id)
                row = conn.execute("DELETE FROM tournament_teams WHERE tournament_id=%s AND team_id=%s RETURNING team_id",(tournament_id,team_id)).fetchone()
                if not row:
                    raise NotFound("El equipo no está inscrito en este torneo.")
        except psycopg.errors.CheckViolation:
            raise Conflict("No se puede retirar un equipo que tiene partidos en este torneo.")
        return jsonify(message="Inscripción retirada correctamente.")

    @app.cli.command("init-competitions")
    def init_competitions():
        with connect() as conn:
            conn.execute((Path(__file__).parent / "migrations/005_competitions.sql").read_text(encoding="utf-8"))
            if conn.execute("SELECT EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid='tournament_teams'::regclass AND attname='snapshot_created_at')").fetchone()[0]:
                apply_snapshots(conn)
        click.echo("Temporadas y torneos preparados. Se conservó el historial de la liga.")

    @app.cli.command("init-snapshots")
    def init_snapshots():
        with connect() as conn:
            apply_snapshots(conn)
        click.echo("Identidades históricas preparadas. Se conservó el historial de la liga.")
