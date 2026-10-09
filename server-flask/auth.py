from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
import re
import secrets

import click
from flask import g, jsonify, redirect, render_template, request, session
from flask.sessions import SecureCookieSession, SessionInterface
from itsdangerous import BadSignature, URLSafeSerializer
from psycopg.types.json import Jsonb
from werkzeug.security import check_password_hash, generate_password_hash


def now():
    return datetime.now(timezone.utc)


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def credential_stamp(secret, password_hash):
    return hmac.new(secret.encode(), password_hash.encode(), hashlib.sha256).hexdigest()


class SessionStore:
    def __init__(self, connect):
        self.connect = connect

    def load(self, token):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT data, expires_at FROM administrator_sessions "
                "WHERE token_hash = %s AND expires_at > CURRENT_TIMESTAMP",
                (token_hash(token),),
            ).fetchone()
        return row

    def delete(self, token):
        with self.connect() as conn:
            conn.execute("DELETE FROM administrator_sessions WHERE token_hash = %s",
                         (token_hash(token),))

    def save(self, token, data, expires_at, new):
        with self.connect() as conn:
            if new:
                conn.execute(
                    "INSERT INTO administrator_sessions "
                    "(token_hash, administrator_id, data, expires_at) VALUES (%s, %s, %s, %s)",
                    (token_hash(token), data.get("admin_id"), Jsonb(data), expires_at),
                )
                return True
            # Updating rather than upserting prevents concurrent requests from
            # recreating a session revoked by logout or password reset.
            result = conn.execute(
                "UPDATE administrator_sessions SET data = %s "
                "WHERE token_hash = %s AND expires_at > CURRENT_TIMESTAMP",
                (Jsonb(data), token_hash(token)),
            )
            return result.rowcount == 1


class ServerSession(SecureCookieSession):
    def __init__(self, data=None, token=None, expires_at=None):
        super().__init__(data)
        self.token = token or secrets.token_urlsafe(32)
        self.expires_at = expires_at
        self.new = token is None
        self.invalid_cookie = False
        self.unavailable = False


class PostgresSessionInterface(SessionInterface):
    def __init__(self, store):
        self.store = store

    def signer(self, app):
        return URLSafeSerializer(app.secret_key, salt="voli-admin-session-v1")

    def open_session(self, app, request):
        cookie = request.cookies.get(self.get_cookie_name(app))
        if not cookie:
            return ServerSession()
        try:
            token = self.signer(app).loads(cookie)
            if not isinstance(token, str) or len(token) != 43:
                raise BadSignature("invalid session identifier")
        except BadSignature:
            result = ServerSession()
            result.invalid_cookie = True
            return result
        try:
            row = self.store.load(token)
        except Exception:
            app.logger.error("Unable to load session")
            result = ServerSession()
            result.unavailable = True
            return result
        if row:
            return ServerSession(row[0], token, row[1])
        result = ServerSession()
        result.invalid_cookie = True
        return result

    def save_session(self, app, session, response):
        name = self.get_cookie_name(app)
        cookie_options = dict(path="/", httponly=True,
                              secure=self.get_cookie_secure(app), samesite="Lax")
        if session.unavailable:
            return
        if not session:
            if session.modified and not session.new:
                try:
                    self.store.delete(session.token)
                except Exception:
                    app.logger.error("Unable to revoke session")
                    response.status_code = 503
                    response.headers.pop("Location", None)
                    response.content_type = "application/json"
                    response.set_data('{"error":"No se pudo cerrar la sesión. Inténtalo de nuevo."}')
                    response.headers["Cache-Control"] = "no-store"
                    return
            if session.modified or session.invalid_cookie:
                response.delete_cookie(name, **cookie_options)
            return
        if not session.modified:
            return
        if session.expires_at is None:
            session.expires_at = now() + timedelta(minutes=15)
        try:
            saved = self.store.save(session.token, dict(session), session.expires_at, session.new)
        except Exception:
            app.logger.error("Unable to save session")
            response.status_code = 503
            response.headers.pop("Location", None)
            response.content_type = "application/json"
            response.set_data('{"error":"No se pudo iniciar la sesión. Inténtalo de nuevo."}')
            response.headers["Cache-Control"] = "no-store"
            response.delete_cookie(name, **cookie_options)
            return
        if not saved:
            response.status_code = 401
            response.headers.pop("Location", None)
            response.content_type = "application/json"
            response.set_data('{"error":"La sesión ha caducado. Inicia sesión de nuevo."}')
            response.headers["Cache-Control"] = "no-store"
            response.delete_cookie(name, **cookie_options)
            return
        response.vary.add("Cookie")
        response.set_cookie(name, self.signer(app).dumps(session.token),
                            expires=session.expires_at, **cookie_options)


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def install_auth(app, connect):
    store = SessionStore(connect)
    app.session_interface = PostgresSessionInterface(store)
    app.extensions["auth_session_store"] = store
    dummy_hash = generate_password_hash(secrets.token_urlsafe(32))

    def auth_error(message, status):
        if request.path.startswith("/api/"):
            return jsonify(error=message), status
        return render_template("login.html", error=message, csrf_token=csrf_token()), status

    @app.before_request
    def protect_administration():
        g.administrator = None
        unsafe = request.method not in {"GET", "HEAD", "OPTIONS"}
        protected = (request.path.startswith("/api/admin/") or request.path == "/api/admin"
                     or request.path == "/api/auth/session"
                     or request.path in {"/admin.html", "/admin.js", "/scheduling.js", "/competitions.js", "/logout"}
                     or (unsafe and request.path != "/login"))
        g.protected_response = protected
        if session.unavailable and (protected or request.path == "/login"):
            return jsonify(error="La sesión no está disponible. Inténtalo de nuevo."), 503
        if protected:
            if session.get("admin_id"):
                with connect() as conn:
                    g.administrator = conn.execute(
                        "SELECT id, username, password_hash FROM administrators WHERE id = %s AND active = TRUE",
                        (session["admin_id"],),
                    ).fetchone()
                if g.administrator and not hmac.compare_digest(
                    session.get("credential_stamp", ""), credential_stamp(app.secret_key, g.administrator[2])
                ):
                    g.administrator = None
            if not g.administrator:
                session.clear()
                if request.path.startswith("/api/"):
                    return jsonify(error="Inicia sesión para acceder a la administración."), 401
                return redirect("/login?motivo=sesion", code=303)
        if unsafe:
            origin = request.headers.get("Origin")
            expected = session.get("csrf_token")
            supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
            if (origin and origin != request.host_url.rstrip("/")) or not (
                isinstance(expected, str) and isinstance(supplied, str)
                and hmac.compare_digest(expected.encode(), supplied.encode())
            ):
                return auth_error("La solicitud no es válida. Recarga la página e inténtalo de nuevo.", 403)

    @app.after_request
    def security_headers(response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; connect-src 'self'; form-action 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
        )
        if (g.get("protected_response", False)
                or request.path.startswith(("/api/admin/", "/api/auth/"))
                or request.path in {"/login", "/logout", "/admin.html", "/admin.js", "/scheduling.js", "/competitions.js"}):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Vary"] = "Cookie"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if response.status_code >= 400:
            response.headers["Cache-Control"] = "no-store"
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def allow_login(username):
        # Shared counters across workers; no raw IP addresses or usernames stored.
        keys = [("ip:" + (request.remote_addr or "unknown"), 30),
                ("account:" + username, 10)]
        allowed = True
        with connect() as conn:
            for value, limit in keys:
                key = hmac.new(app.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()
                count = conn.execute(
                    "INSERT INTO administrator_login_attempts (key_hash, attempts) VALUES (%s, 1) "
                    "ON CONFLICT (key_hash) DO UPDATE SET "
                    "attempts = CASE WHEN administrator_login_attempts.window_start "
                    "< CURRENT_TIMESTAMP - INTERVAL '15 minutes' THEN 1 "
                    "ELSE administrator_login_attempts.attempts + 1 END, "
                    "window_start = CASE WHEN administrator_login_attempts.window_start "
                    "< CURRENT_TIMESTAMP - INTERVAL '15 minutes' THEN CURRENT_TIMESTAMP "
                    "ELSE administrator_login_attempts.window_start END RETURNING attempts",
                    (key,),
                ).fetchone()[0]
                allowed = allowed and count <= limit
        return allowed

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method in {"GET", "HEAD"}:
            return render_template("login.html", csrf_token=csrf_token(), error=None)
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        # Charge malformed attempts to the IP budget too, before password hashing.
        valid_username = bool(re.fullmatch(r"[a-z0-9_.-]{3,64}", username))
        normalized = username if valid_username else "invalid"
        if not allow_login(normalized):
            response = app.make_response(auth_error("Demasiados intentos. Espera 15 minutos e inténtalo de nuevo.", 429))
            response.headers["Retry-After"] = "900"
            return response
        if not valid_username or not 1 <= len(password) <= 128:
            return auth_error("Usuario o contraseña incorrectos.", 401)
        with connect() as conn:
            account = conn.execute(
                "SELECT id, password_hash, active FROM administrators WHERE username = %s",
                (username,),
            ).fetchone()
        valid = check_password_hash(account[1] if account else dummy_hash, password)
        if not account or not valid or not account[2]:
            return auth_error("Usuario o contraseña incorrectos.", 401)
        store.delete(session.token)
        session.clear()
        session.token = secrets.token_urlsafe(32)
        session.new = True
        session.expires_at = now() + app.config["ADMIN_SESSION_LIFETIME"]
        session["admin_id"] = account[0]
        session["credential_stamp"] = credential_stamp(app.secret_key, account[1])
        csrf_token()
        return redirect("/admin.html", code=303)

    @app.post("/logout")
    def logout():
        store.delete(session.token)
        session.clear()
        session.new = True
        return redirect("/login?salida=1", code=303)

    @app.get("/api/auth/session")
    def auth_session():
        return jsonify(username=g.administrator[1], csrf_token=csrf_token())

    @app.cli.command("init-auth")
    def init_auth():
        """Crea las tablas de autenticación sin modificar los datos de la liga."""
        migration = Path(__file__).parent / "migrations" / "001_admin_auth.sql"
        with connect() as conn:
            conn.execute(migration.read_text(encoding="utf-8"))
        click.echo("Tablas de autenticación creadas.")

    @app.cli.command("create-admin")
    @click.option("--username", prompt="Usuario")
    def create_admin(username):
        """Crea un administrador; la contraseña se solicita sin mostrarla."""
        username = username.strip().lower()
        if not re.fullmatch(r"[a-z0-9_.-]{3,64}", username):
            raise click.ClickException("Usa entre 3 y 64 letras, números, puntos, guiones o guiones bajos.")
        password = click.prompt("Contraseña", hide_input=True, confirmation_prompt="Repite la contraseña")
        if not 12 <= len(password) <= 128:
            raise click.ClickException("La contraseña debe tener entre 12 y 128 caracteres.")
        with connect() as conn:
            result = conn.execute(
                "INSERT INTO administrators (username, password_hash) VALUES (%s, %s) "
                "ON CONFLICT (username) DO NOTHING RETURNING id",
                (username, generate_password_hash(password)),
            ).fetchone()
        if not result:
            raise click.ClickException("Ese usuario ya existe.")
        click.echo("Administrador creado correctamente.")

    @app.cli.command("prune-auth")
    def prune_auth():
        """Elimina sesiones caducadas y contadores antiguos."""
        with connect() as conn:
            conn.execute("DELETE FROM administrator_sessions WHERE expires_at <= CURRENT_TIMESTAMP")
            conn.execute("DELETE FROM administrator_login_attempts "
                         "WHERE window_start < CURRENT_TIMESTAMP - INTERVAL '15 minutes'")
        click.echo("Sesiones y contadores caducados eliminados.")

    @app.cli.command("reset-admin-password")
    @click.option("--username", prompt="Usuario")
    def reset_admin_password(username):
        """Cambia una contraseña y revoca todas las sesiones de ese administrador."""
        password = click.prompt("Nueva contraseña", hide_input=True, confirmation_prompt="Repite la contraseña")
        if not 12 <= len(password) <= 128:
            raise click.ClickException("La contraseña debe tener entre 12 y 128 caracteres.")
        with connect() as conn:
            account = conn.execute(
                "UPDATE administrators SET password_hash = %s WHERE username = %s RETURNING id",
                (generate_password_hash(password), username.strip().lower()),
            ).fetchone()
            if not account:
                raise click.ClickException("No se encontró el administrador.")
            conn.execute("DELETE FROM administrator_sessions WHERE administrator_id = %s", (account[0],))
        click.echo("Contraseña actualizada y sesiones cerradas.")
