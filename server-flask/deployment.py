"""Small staging-only transport and readiness helpers."""
import ipaddress
import os
from pathlib import Path
import tempfile

from flask import jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix


class RailwayProxy:
    def __init__(self, app):
        self.app = ProxyFix(app, x_for=0, x_proto=1, x_host=0)

    def __call__(self, environ, start_response):
        # Railway documents X-Real-IP, not an arbitrary client X-Forwarded-For.
        try:
            environ["REMOTE_ADDR"] = str(ipaddress.ip_address(environ.get("HTTP_X_REAL_IP", "")))
        except ValueError:
            pass
        return self.app(environ, start_response)


def configure_proxy(wsgi_app, config):
    if not config["TRUST_PROXY"]:
        return wsgi_app
    if config["PROXY_MODE"] == "railway":
        return RailwayProxy(wsgi_app)
    return ProxyFix(wsgi_app, x_for=1, x_proto=1, x_host=0)


def readiness(app, connect):
    try:
        directory = Path(app.config["TEAM_LOGO_DIRECTORY"])
        mount = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
        if app.config["PROXY_MODE"] == "railway":
            if not mount or not Path(mount).is_mount() or not directory.resolve().is_relative_to(Path(mount).resolve()):
                raise OSError("Volumen no disponible")
        with connect() as conn:
            conn.execute("SELECT 1 FROM tournament_team_identities LIMIT 1").fetchone()
            conn.execute("SELECT 1 FROM administrators LIMIT 1").fetchone()
        with tempfile.TemporaryFile(dir=directory) as probe:
            probe.write(b"ready")
            probe.flush()
        response = jsonify(estado="disponible")
    except Exception:
        # No schema names, paths, connection details or exception text escape.
        response = jsonify(estado="no disponible")
        response.status_code = 503
    response.headers["Cache-Control"] = "no-store"
    return response


def install_deployment(app, connect):
    @app.get("/healthz")
    def healthz():
        if not app.config["STAGING"]:
            return jsonify(error="No se encontró la página."), 404
        return readiness(app, connect)

    @app.get("/robots.txt")
    def robots():
        return ("User-agent: *\nDisallow: /\n" if app.config["STAGING"] else "User-agent: *\nAllow: /\n"), 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.after_request
    def no_index(response):
        if app.config["STAGING"]:
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response
