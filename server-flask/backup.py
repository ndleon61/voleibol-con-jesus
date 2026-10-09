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
    source, logos = Path(source).resolve(), Path(logos).resolve()
    if logos.exists():
        raise ValueError("El directorio de destino debe ser nuevo.")
    manifest = json.loads((source / "manifest.json").read_text())
    if set(manifest) != {"database.dump", "logos.tar.gz"} or any(digest(source / name) != value for name,value in manifest.items()):
        raise ValueError("La copia no supera la comprobación de integridad.")
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
        logos.mkdir(parents=True, mode=0o700)
        with tarfile.open(source / "logos.tar.gz", "r:gz") as archive:
            for item in archive.getmembers():
                if not item.isfile() or not re.fullmatch(r"[a-f0-9]{32}\.webp", item.name) or item.size > 4 * 1024 * 1024:
                    raise ValueError("La copia de logotipos contiene un archivo no permitido.")
                with archive.extractfile(item) as input_file, (logos / item.name).open("xb") as output:
                    shutil.copyfileobj(input_file, output)
                os.chmod(logos / item.name, 0o600)
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
    args = parser.parse_args()
    database = os.environ.get("DATABASE_URL")
    if not database:
        parser.error("Configura DATABASE_URL; utiliza PGPASSFILE para las credenciales.")
    try:
        if args.command == "backup":
            backup(database, args.logos, args.output)
        else:
            restore(args.source, database, args.database_name, args.logos)
    except Exception:
        parser.exit(1, "No se completó la operación. Comprueba la copia, los permisos y la configuración. No se sobrescribió la base original.\n")
    print("Operación completada correctamente.")


if __name__ == "__main__":
    main()
