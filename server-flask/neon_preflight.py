"""Opt-in read-only preflight. Never provisions roles, databases or application data."""
import argparse
import os

import psycopg
from psycopg.conninfo import conninfo_to_dict

TARGET = "voli_staging_2026"
EMPTY_QUERY = """SELECT
    EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema')
    OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
              WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema')
    OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspname !~ '^pg_'
              AND nspname NOT IN ('public','information_schema'))
    OR EXISTS(SELECT 1 FROM pg_extension WHERE extname <> 'plpgsql')"""


def preflight(database, expected_host, expected_role):
    config = conninfo_to_dict(database)
    if (not expected_host or not expected_role or config.get("host") != expected_host
            or "-pooler" in expected_host or "," in expected_host or "/" in expected_host
            or config.get("dbname") != TARGET or config.get("user") != expected_role
            or config.get("sslmode") != "verify-full" or config.get("sslrootcert") != "system"
            or config.get("channel_binding") != "require"):
        raise ValueError("Configura el destino directo confirmado con SSL verificado.")
    # Startup protection applies before any SQL; the transaction also explicitly stays read-only.
    with psycopg.connect(database, connect_timeout=5,
            options="-c default_transaction_read_only=on -c statement_timeout=15000 "
                    "-c lock_timeout=5000 -c idle_in_transaction_session_timeout=30000") as conn:
        if not conn.pgconn.ssl_in_use or conn.info.host != expected_host:
            raise ValueError("No se verificó el transporte seguro esperado.")
        conn.execute("SET TRANSACTION READ ONLY")
        name, version, read_only, role = conn.execute(
            "SELECT current_database(),current_setting('server_version_num')::integer,"
            "current_setting('transaction_read_only'),current_user").fetchone()
        if name != TARGET or not 180006 <= version < 190000 or read_only != "on" or role != expected_role:
            raise ValueError("La identidad o versión del destino no coincide.")
        if conn.execute(EMPTY_QUERY).fetchone()[0]:
            raise ValueError("El destino contiene objetos. No se debe inicializar ni restaurar.")
        permissions = conn.execute("SELECT has_database_privilege(current_user,current_database(),'CONNECT'),"
            "has_schema_privilege(current_user,'public','USAGE'),"
            "has_schema_privilege(current_user,'public','CREATE'),"
            "pg_has_role(current_user,nspowner,'USAGE') FROM pg_namespace WHERE nspname='public'").fetchone()
        if not permissions or not all(permissions):
            raise ValueError("El rol no dispone de los permisos de mantenimiento necesarios.")
        # No writes occurred. Roll back even the read-only transaction explicitly.
        conn.rollback()
    return {"base_confirmada": True, "version": version, "vacia": True,
            "ssl_verificado": True, "solo_lectura": True, "permisos_mantenimiento": True}


def main():
    parser = argparse.ArgumentParser(description="Preflight Neon estrictamente de solo lectura.")
    parser.add_argument("--read-only-approved", action="store_true", required=True)
    args = parser.parse_args()
    try:
        result = preflight(os.environ["NEON_PREFLIGHT_DATABASE_URL"],
                           os.environ["NEON_EXPECTED_HOST"], os.environ["NEON_EXPECTED_ROLE"])
    except Exception:
        parser.exit(1, "Preflight rechazado. Revisa en privado identidad, SSL, permisos y destino vacío. No se mostraron secretos.\n")
    print("Preflight de solo lectura completado: destino vacío, SSL, versión y permisos confirmados.")
    print("La correspondencia del endpoint con el proyecto y rama debe confirmarse en la consola Neon.")


if __name__ == "__main__":
    main()
