import hashlib
import json
import os
from pathlib import Path
import re

from flask import current_app
from werkzeug.exceptions import Conflict


def prepare_logos(conn, tournament_id=None):
    missing = ""
    if tournament_id is None and conn.execute("SELECT EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid='tournament_teams'::regclass AND attname='team_logo_snapshot')").fetchone()[0]:
        missing = " AND r.team_logo_snapshot IS NULL"
    rows = conn.execute(
        "SELECT t.id,t.logo_path FROM teams t WHERE EXISTS (SELECT 1 FROM tournament_teams r "
        "JOIN tournaments c ON c.id=r.tournament_id WHERE r.team_id=t.id AND "
        "(%s::integer IS NULL AND c.status IN('completed','archived') OR r.tournament_id=%s)" + missing + ") "
        "ORDER BY t.id FOR SHARE", (tournament_id,tournament_id),
    ).fetchall()
    mapping = {}
    from teams import LEGACY_LOGOS, validate_logo
    from werkzeug.datastructures import FileStorage
    directory = Path(current_app.config["TEAM_LOGO_DIRECTORY"])
    for team_id, url in rows:
        if not url:
            mapping[str(team_id)] = ""
            continue
        if re.fullmatch(r"/team-logos/[a-f0-9]{32}\.webp",url):
            path = directory / url.rsplit("/",1)[1]
            if path.is_symlink() or not path.is_file():
                raise Conflict("Falta un logotipo del torneo. Restáuralo antes de cerrar la competición.")
            mapping[str(team_id)] = url
            continue
        if url not in LEGACY_LOGOS.values():
            raise Conflict("El logotipo no pertenece al almacenamiento autorizado.")
        source = Path(current_app.root_path).parent / url.lstrip("/")
        if source.is_symlink() or not source.is_file():
            raise Conflict("Falta un logotipo original. Restáuralo antes de cerrar la competición.")
        with source.open("rb") as file:
            content = validate_logo(FileStorage(stream=file,filename=source.name))
        name = hashlib.sha256(content).hexdigest()[:32]+".webp"
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        destination = directory/name
        try:
            descriptor = os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError:
            if destination.is_symlink() or destination.read_bytes()!=content:
                raise Conflict("No se pudo preservar el logotipo de forma segura.")
        else:
            try:
                with os.fdopen(descriptor,"wb") as file:
                    file.write(content)
            except OSError:
                destination.unlink(missing_ok=True)
                raise
        mapping[str(team_id)] = "/team-logos/"+name
    conn.execute("SELECT set_config('voli.snapshot_logos',%s,true)",(json.dumps(mapping),))


def apply_snapshots(conn):
    conn.execute("LOCK TABLE teams,tournaments,tournament_teams IN SHARE ROW EXCLUSIVE MODE")
    prepare_logos(conn)
    conn.execute((Path(__file__).parent/"migrations/006_team_snapshots.sql").read_text())
