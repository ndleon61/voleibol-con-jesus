"""Explicit, transactional bootstrap for a new staging database, never server startup."""
import os
from pathlib import Path
import re

import click
import psycopg
from psycopg.conninfo import conninfo_to_dict

from neon_preflight import EMPTY_QUERY
from snapshots import apply_snapshots


def initialize_empty(conn, expected_name):
    conn.execute("SELECT pg_advisory_xact_lock(86100310)")
    name, version = conn.execute(
        "SELECT current_database(),current_setting('server_version_num')::integer"
    ).fetchone()
    if name != expected_name or not re.fullmatch(r"voli_staging_[a-z0-9_]{1,40}", name):
        raise ValueError("La base no coincide con el destino staging confirmado.")
    if not 180006 <= version < 190000:
        raise ValueError("La instalación requiere PostgreSQL 18.6 o posterior de la rama 18.")
    if conn.execute(EMPTY_QUERY).fetchone()[0]:
        raise ValueError("La base debe estar vacía. No se sobrescribió ningún dato.")
    conn.execute("SET LOCAL search_path TO public")
    directory = Path(__file__).parent / "migrations"
    for name in ("000_fresh_base.sql", "001_admin_auth.sql", "002_team_management.sql",
                 "003_scheduling.sql", "004_business_rules.sql", "005_competitions.sql"):
        conn.execute((directory / name).read_text(encoding="utf-8"))
    # The legacy migration creates placeholders for existing installations.
    # Only this new, empty transaction may remove them; no imported history exists.
    conn.execute("ALTER TABLE jornadas ALTER COLUMN tournament_id DROP DEFAULT")
    conn.execute("DELETE FROM tournaments WHERE legacy_key='original_league'")
    conn.execute("DELETE FROM seasons WHERE legacy_key='original_league'")
    apply_snapshots(conn)
    conn.execute((directory / "007_match_formats.sql").read_text(encoding="utf-8"))
    for table in ("matches", "match_sets"):
        names = conn.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid=%s::regclass AND NOT convalidated",
            (table,),
        ).fetchall()
        for (constraint,) in names:
            conn.execute(psycopg.sql.SQL("ALTER TABLE {} VALIDATE CONSTRAINT {}").format(
                psycopg.sql.Identifier(table), psycopg.sql.Identifier(constraint)))


def install_initialization(app, connect):
    @app.cli.command("init-staging")
    @click.option("--database-name", required=True)
    @click.option("--empty-database-confirmed", is_flag=True, required=True)
    def init_staging(database_name, empty_database_confirmed):
        """Inicializa una base staging vacía; nunca importa datos locales."""
        config = conninfo_to_dict(os.environ.get("DATABASE_URL", ""))
        if (not empty_database_confirmed
                or not re.fullmatch(r"voli_staging_[a-z0-9_]{1,40}", database_name)
                or config.get("dbname") != database_name
                or config.get("sslmode") != "verify-full"
                or "-pooler" in config.get("host", "")):
            raise click.ClickException("Confirma la base staging vacía, conexión directa y SSL verificado.")
        try:
            with connect() as conn:
                if "-pooler" in conn.info.host:
                    raise ValueError("La conexión de mantenimiento debe ser directa.")
                initialize_empty(conn, database_name)
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        except psycopg.Error:
            raise click.ClickException("No se pudo crear el esquema. La transacción se revirtió; revisa los permisos en privado.") from None
        click.echo("Esquema staging creado sin datos de la liga. Crea ahora un administrador.")
