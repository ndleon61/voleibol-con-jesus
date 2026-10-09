from io import BytesIO
from pathlib import Path
import re
import secrets
import warnings
import os

import click
from flask import jsonify, request, send_from_directory
from PIL import Image, ImageOps, UnidentifiedImageError
import psycopg
from validation import validate_name
from competitions import requested_tournament
from reliability import catalog_page


MAX_LOGO_BYTES = 2 * 1024 * 1024
MAX_LOGO_PIXELS = 16_000_000
MAX_NAME_LENGTH = 100
LOGO_FILENAME = re.compile(r"[a-f0-9]{32}\.webp")
LEGACY_LOGOS = {
    "Los Abusadores": "/media/los_abusadores.JPG",
    "Los Lobos": "/media/los_lobos.JPG",
    "Los Defensores": "/media/polea.JPG",
    "La Furia Roja": "/media/la_furia_roja.JPG",
    "La Ofensiva Aplastante": "/media/la_ofensiva_aplastante.JPG",
}


class LogoValidationError(ValueError):
    pass


def team_json(row):
    return {"id": row[0], "name": row[1], "logo": row[2] or ""}


def validate_logo(upload):
    raw = upload.stream.read(MAX_LOGO_BYTES + 1)
    if len(raw) > MAX_LOGO_BYTES:
        raise ValueError("El logotipo no puede superar los 2 MB.")
    if not raw:
        raise ValueError("El archivo del logotipo está vacío.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise LogoValidationError("El logotipo debe ser una imagen JPEG, PNG o WebP.")
                if image.width * image.height > MAX_LOGO_PIXELS:
                    raise LogoValidationError("La imagen es demasiado grande. Usa una imagen de hasta 16 millones de píxeles.")
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                image.load()
                resized = ImageOps.exif_transpose(image)
                resized.thumbnail((1024, 1024))
                resized = resized.convert("RGBA" if "A" in resized.getbands() or "transparency" in resized.info else "RGB")
                output = BytesIO()
                resized.save(output, format="WEBP", quality=85, method=4)
                return output.getvalue()
    except LogoValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("El archivo no es una imagen válida. Usa JPEG, PNG o WebP.") from error


def install_teams(app, connect):
    app.config.setdefault("TEAM_LOGO_DIRECTORY", os.environ.get("TEAM_LOGO_DIRECTORY", str(Path(app.instance_path) / "team-logos")))

    @app.before_request
    def upload_request_limit():
        if request.method in {"POST", "PUT"} and (
            request.path == "/api/admin/teams"
            or re.fullmatch(r"/api/admin/teams/\d+", request.path)
        ):
            request.max_content_length = MAX_LOGO_BYTES + 64 * 1024

    def store_logo(content):
        directory = Path(app.config["TEAM_LOGO_DIRECTORY"])
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        filename = secrets.token_hex(16) + ".webp"
        created = False
        try:
            descriptor = os.open(directory / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(descriptor, "wb") as file:
                file.write(content)
        except OSError:
            if created:
                (directory / filename).unlink(missing_ok=True)
            raise
        return "/team-logos/" + filename

    def remove_logo_file(url):
        if not url or not url.startswith("/team-logos/"):
            return
        filename = url.removeprefix("/team-logos/")
        if LOGO_FILENAME.fullmatch(filename):
            try:
                (Path(app.config["TEAM_LOGO_DIRECTORY"]) / filename).unlink(missing_ok=True)
            except OSError:
                app.logger.error("Unable to remove obsolete team logo")

    def read_team_form():
        data = request.get_json(silent=True) if request.is_json else request.form
        if data is None or not hasattr(data, "get"):
            raise ValueError("La solicitud no es válida.")
        name = validate_name(data.get("name"))
        removal = data.get("remove_logo", False)
        if not isinstance(removal, (bool, str)) or removal not in (True, False, "true", "false", ""):
            raise ValueError("La opción de eliminar el logotipo no es válida.")
        removal = removal is True or removal == "true"
        upload = request.files.get("logo")
        upload = upload if upload and upload.filename else None
        if removal and upload:
            raise ValueError("Elige entre reemplazar o eliminar el logotipo.")
        content = validate_logo(upload) if upload else None
        return name, removal, content

    @app.get("/api/teams")
    def list_public_teams(tournament_id=None):
        with connect() as conn:
            scope = requested_tournament(conn,tournament_id)
            rows = conn.execute("SELECT t.id, t.name, t.logo_path FROM tournament_team_identities t WHERE t.tournament_id=COALESCE(%s,(SELECT id FROM tournaments WHERE is_public=TRUE)) ORDER BY t.id",(scope,)).fetchall()
        return jsonify([team_json(row) for row in rows])

    app.add_url_rule('/api/tournaments/<int:tournament_id>/teams','tournament_public_teams',list_public_teams)

    @app.get("/api/admin/teams")
    def list_admin_teams():
        limit,offset = catalog_page()
        with connect() as conn:
            rows = conn.execute(
                "SELECT t.id, t.name, t.logo_path, EXISTS ("
                "SELECT 1 FROM matches m WHERE m.team1_id = t.id OR m.team2_id = t.id) "
                "FROM teams t ORDER BY t.id LIMIT %s OFFSET %s", (limit,offset),
            ).fetchall()
        return jsonify([{**team_json(row), "has_matches": row[3]} for row in rows])

    def save_team(team_id=None):
        new_logo = None
        old_logo = None
        try:
            name, removal, content = read_team_form()
            with connect() as conn:
                if team_id is not None:
                    existing = conn.execute(
                        "SELECT id, name, logo_path FROM teams WHERE id = %s FOR UPDATE", (team_id,),
                    ).fetchone()
                    if not existing:
                        return jsonify(error="No se encontró el equipo."), 404
                    old_logo = existing[2]
                logo = None if removal else old_logo
                if content is not None:
                    new_logo = store_logo(content)
                    logo = new_logo
                if team_id is None:
                    row = conn.execute(
                        "INSERT INTO teams (name, logo_path) VALUES (%s, %s) RETURNING id, name, logo_path",
                        (name, logo),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "UPDATE teams SET name = %s, logo_path = %s WHERE id = %s RETURNING id, name, logo_path",
                        (name, logo, team_id),
                    ).fetchone()
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except psycopg.errors.UniqueViolation:
            remove_logo_file(new_logo)
            return jsonify(error="Ya existe un equipo con ese nombre."), 409
        except Exception:
            remove_logo_file(new_logo)
            raise
        # Successful assets are immutable and retained for historical references.
        message = "Equipo registrado correctamente." if team_id is None else "Equipo actualizado correctamente."
        return jsonify(message=message, team=team_json(row)), 201 if team_id is None else 200

    app.add_url_rule("/api/admin/teams", "create_team", save_team, methods=["POST"])
    app.add_url_rule("/api/admin/teams/<int:team_id>", "update_team", save_team, methods=["PUT"])

    @app.delete("/api/admin/teams/<int:team_id>")
    def delete_team(team_id):
        try:
            with connect() as conn:
                team = conn.execute(
                    "SELECT id, name, logo_path FROM teams WHERE id = %s FOR UPDATE", (team_id,),
                ).fetchone()
                if not team:
                    return jsonify(error="No se encontró el equipo."), 404
                if conn.execute(
                    "SELECT EXISTS (SELECT 1 FROM matches WHERE team1_id = %s OR team2_id = %s)",
                    (team_id, team_id),
                ).fetchone()[0]:
                    return jsonify(error="No se puede eliminar este equipo porque tiene partidos registrados. Se conserva su historial."), 409
                conn.execute("DELETE FROM teams WHERE id = %s", (team_id,))
        except psycopg.errors.ForeignKeyViolation:
            return jsonify(error="No se puede eliminar este equipo porque tiene registros asociados. Se conserva su historial."), 409
        return jsonify(message="Equipo eliminado correctamente.")

    @app.get("/team-logos/<filename>")
    def uploaded_team_logo(filename):
        if not LOGO_FILENAME.fullmatch(filename):
            return jsonify(error="No se encontró el logotipo."), 404
        if (Path(app.config["TEAM_LOGO_DIRECTORY"]) / filename).is_symlink():
            return jsonify(error="No se encontró el logotipo."), 404
        return send_from_directory(app.config["TEAM_LOGO_DIRECTORY"], filename,
                                   mimetype="image/webp", max_age=31536000)

    @app.cli.command("init-teams")
    def init_teams():
        """Añade logotipos y protección contra nombres duplicados sin borrar datos."""
        migration = Path(__file__).parent / "migrations" / "002_team_management.sql"
        try:
            with connect() as conn:
                already_initialized = conn.execute(
                    "SELECT to_regclass('teams_name_normalized_unique') IS NOT NULL"
                ).fetchone()[0]
                conn.execute(migration.read_text(encoding="utf-8"))
                if not already_initialized:
                    for name, logo in LEGACY_LOGOS.items():
                        conn.execute("UPDATE teams SET logo_path = %s WHERE name = %s AND logo_path IS NULL", (logo, name))
        except psycopg.errors.UniqueViolation as error:
            raise click.ClickException("Hay equipos con nombres duplicados. Revisa sus nombres antes de aplicar la migración; no se ha eliminado ningún equipo.") from error
        click.echo("Gestión de equipos preparada. Se conservaron los datos de la liga.")
