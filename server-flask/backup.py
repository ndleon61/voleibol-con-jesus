"""Offline, matched database/logo backups; restores only to a newly created database."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def run(command, database):
    env = dict(os.environ, PGDATABASE=database)
    if command[0] in {"pg_restore", "pg_dump"}:
        config = conninfo_to_dict(database)
        password = config.pop("password", None)
        if password is not None:
            env["PGPASSWORD"] = password
        command = [*command, "--dbname=" + make_conninfo(**config)]
    # Credentials stay in the child environment or PGPASSFILE, never argv/logs.
    result = subprocess.run(command, env=env, capture_output=True, timeout=600)
    if result.returncode:
        raise RuntimeError("Falló una herramienta PostgreSQL. Revisa permisos, conexión y versión; no se mostró información sensible.")


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def verify_bundle(source):
    source = Path(source).resolve()
    manifest = json.loads((source / "manifest.json").read_text())
    if set(manifest) != {"database.dump", "logos.tar.gz"} or any(
        digest(source / name) != value for name, value in manifest.items()
    ):
        raise ValueError("La copia no supera la comprobación de integridad.")
    with tarfile.open(source / "logos.tar.gz", "r:gz") as archive:
        names = set()
        for item in archive.getmembers():
            if (not item.isfile() or not re.fullmatch(r"[a-f0-9]{32}\.webp", item.name)
                    or item.size > 4 * 1024 * 1024 or item.name in names):
                raise ValueError("La copia de logotipos contiene un archivo no permitido.")
            names.add(item.name)
    return source


def restore_media(source, logos):
    source = verify_bundle(source)
    logos = Path(logos)
    if logos.is_symlink() or (logos.exists() and (not logos.is_dir() or any(logos.iterdir()))):
        raise ValueError("El directorio de logotipos debe estar vacío y no ser un enlace.")
    logos.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tarfile.open(source / "logos.tar.gz", "r:gz") as archive:
        for item in archive.getmembers():
            with archive.extractfile(item) as input_file, (logos / item.name).open("xb") as output:
                shutil.copyfileobj(input_file, output)
            os.chmod(logos / item.name, 0o600)


def restore_empty(source, database, expected_name):
    """Managed PostgreSQL: never CREATE/DROP/clean; reject any populated target."""
    source = verify_bundle(source)
    config = conninfo_to_dict(database)
    if (not re.fullmatch(r"voli_staging_[a-z0-9_]{1,40}", expected_name)
            or config.get("dbname") != expected_name or "-pooler" in config.get("host", "")
            or config.get("sslmode") != "verify-full"):
        raise ValueError("Utiliza la base dedicada voli_staging_, conexión directa y SSL verificado.")
    with psycopg.connect(database, connect_timeout=5, autocommit=True,
                         options="-c statement_timeout=15000 -c lock_timeout=5000") as conn:
        if "-pooler" in conn.info.host:
            raise ValueError("La conexión de mantenimiento debe ser directa.")
        conn.execute("SELECT pg_advisory_lock(86100310)")
        if conn.execute("SELECT current_database()").fetchone()[0] != expected_name:
            raise ValueError("La base conectada no coincide con el destino confirmado.")
        occupied = conn.execute("""
            SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                          WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema')
                OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                          WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema')
                OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspname !~ '^pg_'
                          AND nspname NOT IN ('public','information_schema'))
                OR EXISTS(SELECT 1 FROM pg_extension WHERE extname <> 'plpgsql')
        """).fetchone()[0]
        if occupied:
            raise ValueError("La base de destino no está vacía. No se sobrescribió ningún dato.")
        run(["pg_restore", "--no-password", "--no-owner", "--no-privileges", "--exit-on-error",
             "--single-transaction", str(source / "database.dump")], database)
        # Restore account credentials, never operating sessions or rate-limit state.
        with conn.transaction():
            conn.execute("DELETE FROM administrator_sessions")
            conn.execute("DELETE FROM administrator_login_attempts")


def verify_media(source, logos, database):
    source, logos = verify_bundle(source), Path(logos)
    with tarfile.open(source / "logos.tar.gz", "r:gz") as archive:
        for item in archive.getmembers():
            path = logos / item.name
            with archive.extractfile(item) as original:
                if path.is_symlink() or not path.is_file() or digest(path) != hashlib.file_digest(original, "sha256").hexdigest():
                    raise ValueError("Un logotipo no coincide con la copia original.")
    with psycopg.connect(database, connect_timeout=5) as conn:
        references = conn.execute("SELECT logo_path FROM teams UNION SELECT team_logo_snapshot FROM tournament_teams").fetchall()
    for (url,) in references:
        if url and url.startswith("/team-logos/"):
            name = url.removeprefix("/team-logos/")
            if not re.fullmatch(r"[a-f0-9]{32}\.webp", name) or not (logos / name).is_file() or (logos / name).is_symlink():
                raise ValueError("Falta un logotipo actual o histórico referenciado por la base.")


def database_fingerprint(database):
    with psycopg.connect(database, connect_timeout=5) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        tables = conn.execute("""SELECT schemaname, tablename FROM pg_tables
            WHERE schemaname !~ '^pg_' AND schemaname <> 'information_schema'
              AND tablename NOT IN ('administrator_sessions','administrator_login_attempts')
            ORDER BY 1,2""").fetchall()
        result = {}
        for schema, table in tables:
            query = sql.SQL("SELECT md5(row_to_json(t)::text) FROM {}.{} t ORDER BY 1").format(sql.Identifier(schema), sql.Identifier(table))
            fingerprint = hashlib.sha256()
            count = 0
            with conn.cursor(name="verify_rows") as cursor:
                cursor.execute(query)
                for (row_hash,) in cursor:
                    fingerprint.update(row_hash.encode("ascii"))
                    count += 1
            result[(schema, table)] = (count, fingerprint.hexdigest())
        sequences = conn.execute("SELECT schemaname, sequencename FROM pg_sequences WHERE schemaname !~ '^pg_' ORDER BY 1,2").fetchall()
        for schema, name in sequences:
            query = sql.SQL("SELECT last_value,is_called FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(name))
            result[(schema, name)] = ("sequence", *conn.execute(query).fetchone())
        return result


def backup(database, logos, destination):
    logos, destination = Path(logos).resolve(), Path(destination).resolve()
    if not logos.is_dir():
        raise ValueError("El directorio de logotipos no existe.")
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(destination, 0o700)
    try:
        run(["pg_dump", "--no-password", "--format=custom", "--file=" + str(destination / "database.dump")], database)
        with tarfile.open(destination / "logos.tar.gz", "w:gz") as archive:
            for path in sorted(logos.iterdir()):
                if path.is_symlink() or not path.is_file() or not re.fullmatch(r"[a-f0-9]{32}\.webp", path.name):
                    raise ValueError("El directorio contiene un archivo inesperado; no se completó la copia.")
                archive.add(path, arcname=path.name)
        manifest = {name:digest(destination / name) for name in ("database.dump", "logos.tar.gz")}
        (destination / "manifest.json").write_text(json.dumps(manifest), encoding="ascii")
        for path in destination.iterdir():
            os.chmod(path, 0o600)
    except Exception:
        shutil.rmtree(destination)
        raise


def restore(source, database, target_name, logos):
    if not re.fullmatch(r"voli_restore_[a-z0-9_]{1,40}", target_name):
        raise ValueError("La base de destino debe comenzar por voli_restore_ y tener un nombre válido.")
    source, logos = verify_bundle(source), Path(logos).resolve()
    if logos.exists():
        raise ValueError("El directorio de destino debe ser nuevo.")
    config = conninfo_to_dict(database)
    if config.get("dbname") == target_name:
        raise ValueError("No se puede restaurar sobre la base de origen.")
    target = make_conninfo(database, dbname=target_name)
    maintenance = make_conninfo(database, dbname="postgres")
    created = False
    try:
        with psycopg.connect(maintenance, autocommit=True) as conn:
            # CREATE fails if it already exists. Never use --clean or overwrite.
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(target_name)))
        created = True
        run(["pg_restore", "--no-password", "--no-owner", "--no-privileges", "--exit-on-error", "--single-transaction", str(source / "database.dump")], target)
        restore_media(source, logos)
        # Never restore live administrator sessions to an operating instance.
        with psycopg.connect(target) as conn:
            conn.execute("DELETE FROM administrator_sessions")
            conn.execute("DELETE FROM administrator_login_attempts")
    except Exception:
        if created:
            with psycopg.connect(maintenance, autocommit=True) as conn:
                conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target_name)))
            if logos.exists():
                shutil.rmtree(logos)
        raise
    return target


def main():
    parser = argparse.ArgumentParser(description="Copias de seguridad de la liga y recuperación aislada.")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("backup")
    create.add_argument("--logos", required=True)
    create.add_argument("--output", required=True)
    create.add_argument("--maintenance-confirmed", action="store_true", required=True)
    recover = sub.add_parser("restore")
    recover.add_argument("--source", required=True)
    recover.add_argument("--database-name", required=True)
    recover.add_argument("--logos", required=True)
    managed = sub.add_parser("restore-empty")
    managed.add_argument("--source", required=True)
    managed.add_argument("--database-name", required=True)
    managed.add_argument("--empty-target-confirmed", action="store_true", required=True)
    media = sub.add_parser("restore-media")
    media.add_argument("--source", required=True)
    media.add_argument("--logos", required=True)
    verify = sub.add_parser("verify-media")
    verify.add_argument("--source", required=True)
    verify.add_argument("--logos", required=True)
    sub.add_parser("verify-transfer")
    args = parser.parse_args()
    database = os.environ.get("DATABASE_URL")
    if not database and args.command != "restore-media":
        parser.error("Configura DATABASE_URL; utiliza PGPASSFILE para las credenciales.")
    try:
        if args.command == "backup":
            backup(database, args.logos, args.output)
        elif args.command == "restore":
            restore(args.source, database, args.database_name, args.logos)
        elif args.command == "restore-empty":
            restore_empty(args.source, database, args.database_name)
        elif args.command == "restore-media":
            restore_media(args.source, args.logos)
        elif args.command == "verify-media":
            verify_media(args.source, args.logos, database)
        else:
            original = os.environ.get("SOURCE_DATABASE_URL")
            if not original or database_fingerprint(original) != database_fingerprint(database):
                raise ValueError("La base migrada no coincide con el origen detenido.")
    except Exception:
        parser.exit(1, "No se completó la operación. Comprueba la copia, los permisos y la configuración. No se sobrescribió la base original.\n")
    print("Operación completada correctamente.")


if __name__ == "__main__":
    main()
