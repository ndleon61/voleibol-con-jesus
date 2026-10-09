import os
import re
from datetime import timedelta
from psycopg.conninfo import conninfo_to_dict


def settings(environ=None):
    env = os.environ if environ is None else environ
    secret = env.get("FLASK_SECRET_KEY", "")
    if len(secret) < 32:
        raise RuntimeError("Configura FLASK_SECRET_KEY con una clave aleatoria de al menos 32 caracteres.")
    environment = env.get("APP_ENV", "development")
    if environment not in {"development", "production"}:
        raise RuntimeError("APP_ENV debe ser development o production.")
    production = environment == "production"
    if env.get("STAGING", "0") not in {"0", "1"}:
        raise RuntimeError("STAGING debe ser 0 o 1.")
    staging = env.get("STAGING") == "1"
    if staging and not production:
        raise RuntimeError("Staging requiere APP_ENV=production.")
    proxy_mode = env.get("PROXY_MODE", "standard")
    if proxy_mode not in {"standard", "railway"}:
        raise RuntimeError("PROXY_MODE debe ser standard o railway.")
    if proxy_mode == "railway" and (not staging or env.get("TRUST_PROXY") != "1"):
        raise RuntimeError("El proxy Railway requiere STAGING=1 y TRUST_PROXY=1.")
    if staging:
        try:
            database = conninfo_to_dict(env.get("DATABASE_URL", ""))
        except Exception:
            raise RuntimeError("La configuración PostgreSQL no es válida.") from None
        if (database.get("sslmode") != "verify-full" or not database.get("host")
                or database.get("sslrootcert") != "system"
                or database.get("channel_binding") != "require"):
            raise RuntimeError("Staging requiere un host PostgreSQL con sslmode=verify-full, sslrootcert=system y channel_binding=require.")
        if "-pooler" in database["host"]:
            raise RuntimeError("Utiliza una conexión directa para esta configuración de staging.")
        if not env.get("TEAM_LOGO_DIRECTORY", "").startswith("/"):
            raise RuntimeError("Staging requiere un directorio absoluto de logotipos persistentes.")
    hosts = [host.strip() for host in env.get("TRUSTED_HOSTS", "").split(",") if host.strip()]
    label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    if any(len(host.lstrip(".")) > 253 or not re.fullmatch(r"\.?" + label + r"(?:\." + label + r")*",host) for host in hosts):
        raise RuntimeError("TRUSTED_HOSTS debe contener nombres de host sin esquema, puerto ni comodines.")
    if env.get("TRUST_PROXY", "0") not in {"0", "1"}:
        raise RuntimeError("TRUST_PROXY debe ser 0 o 1.")
    if production and (not env.get("DATABASE_URL", "").strip() or not hosts):
        raise RuntimeError("En producción debes configurar DATABASE_URL y TRUSTED_HOSTS.")
    if production and env.get("FLASK_DEBUG", "0") not in {"0", ""}:
        raise RuntimeError("La depuración no está permitida en producción.")
    return dict(
        SECRET_KEY=secret, PRODUCTION=production, STAGING=staging, PROXY_MODE=proxy_mode,
        SESSION_COOKIE_NAME="__Host-voli_session" if production else "voli_session",
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=production,
        SESSION_COOKIE_SAMESITE="Lax", ADMIN_SESSION_LIFETIME=timedelta(hours=2),
        MAX_CONTENT_LENGTH=64 * 1024, MAX_FORM_MEMORY_SIZE=128 * 1024,
        MAX_FORM_PARTS=20, TRUSTED_HOSTS=hosts or None,
    )
