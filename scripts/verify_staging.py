"""Read-only HTTPS smoke check; optional prompted login/logout, no league writes."""
import argparse
import getpass
import hashlib
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, HTTPCookieProcessor, HTTPRedirectHandler, Request


def checked_url(value):
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError("Utiliza únicamente el origen HTTPS público, sin credenciales.")
    return value.rstrip("/")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CSRFParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.token = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") == "csrf_token":
            self.token = attrs.get("value")


def verify(origin, login=False):
    opener = build_opener(HTTPCookieProcessor(CookieJar()), NoRedirect())

    def fetch(path, expected=200, data=None):
        try:
            response = opener.open(Request(origin + path, data=data), timeout=30)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            if response.status != expected:
                raise ValueError("Una comprobación HTTP no obtuvo el estado esperado.")
            if "noindex" not in response.headers.get("X-Robots-Tag", ""):
                raise ValueError("Falta la protección contra indexación de staging.")
            if "default-src 'self'" not in response.headers.get("Content-Security-Policy", ""):
                raise ValueError("Falta la política de seguridad de contenido.")
            return body, response.headers

    fetch("/")
    fetch("/healthz")
    robots, _ = fetch("/robots.txt")
    if b"Disallow: /" not in robots:
        raise ValueError("robots.txt no bloquea la indexación.")
    state = {}
    for path in ("/api/seasons?limit=500", "/api/tournaments?limit=500", "/api/teams", "/api/jornadas", "/api/standings"):
        body, _ = fetch(path)
        json.loads(body)
        state[path] = hashlib.sha256(body).hexdigest()
    teams = json.loads(fetch("/api/teams")[0])
    for team in teams:
        logo = team.get("logo")
        if logo:
            if not logo.startswith(("/team-logos/", "/media/")) or ".." in logo:
                raise ValueError("Referencia de logotipo inesperada.")
            body, _ = fetch(logo)
            state[logo] = hashlib.sha256(body).hexdigest()
    fetch("/api/admin/stats", 401)
    _, headers = fetch("/admin.html", 303)
    if not headers.get("Location", "").startswith("/login"):
        raise ValueError("La administración no redirige al acceso.")
    body, headers = fetch("/login")
    if "no-store" not in headers.get("Cache-Control", ""):
        raise ValueError("La página de acceso permite caché.")
    if login:
        parser = CSRFParser()
        parser.feed(body.decode())
        if not parser.token:
            raise ValueError("Falta el token CSRF.")
        username = input("Usuario administrador: ")
        password = getpass.getpass("Contraseña: ")
        _, headers = fetch("/login", 303, urlencode(dict(username=username, password=password, csrf_token=parser.token)).encode())
        del password
        cookie = headers.get("Set-Cookie", "")
        if "Secure" not in cookie or "HttpOnly" not in cookie or "SameSite=Lax" not in cookie:
            raise ValueError("La cookie de sesión no es segura.")
        fetch("/admin.html")
        session = json.loads(fetch("/api/auth/session")[0])
        fetch("/logout", 303, urlencode(dict(csrf_token=session["csrf_token"])).encode())
        fetch("/api/admin/stats", 401)
    return state


def main():
    parser = argparse.ArgumentParser(description="Verifica staging sin modificar registros de la liga.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--record", type=Path)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    try:
        state = verify(checked_url(args.url), args.login)
        if args.compare and json.loads(args.compare.read_text()) != state:
            raise ValueError("Cambió el contenido público tras el reinicio.")
        if args.record:
            with args.record.open("x") as output:
                os.chmod(args.record, 0o600)
                json.dump(state, output, sort_keys=True)
    except Exception:
        parser.exit(1, "La verificación no se completó. Revisa HTTPS, configuración y disponibilidad; no se mostraron secretos.\n")
    print("Verificación de staging completada correctamente.")


if __name__ == "__main__":
    main()
