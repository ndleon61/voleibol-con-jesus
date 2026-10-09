import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import secrets
import tarfile
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_hex(32))
import app as backend
from backup import restore_empty, restore_media, verify_bundle, verify_media
from configuration import settings
from deployment import RailwayProxy


class StagingTests(unittest.TestCase):
    def config(self, **changes):
        return {"FLASK_SECRET_KEY":secrets.token_hex(32), "APP_ENV":"production", "STAGING":"1",
                "DATABASE_URL":"host=db.example dbname=voli_staging_test sslmode=verify-full sslrootcert=system channel_binding=require",
                "TRUSTED_HOSTS":"staging.example,healthcheck.railway.app", "TEAM_LOGO_DIRECTORY":"/data/team-logos", **changes}

    def test_staging_requires_ssl_direct_connection_and_persistent_media(self):
        base = self.config()
        for changes in ({"STAGING":"yes"}, {"APP_ENV":"development"}, {"DATABASE_URL":"dbname=test"},
                        {"DATABASE_URL":"host=db-pooler.example sslmode=verify-full"},
                        {"DATABASE_URL":"host=db.example sslmode=require"}, {"TEAM_LOGO_DIRECTORY":"relative"},
                        {"DATABASE_URL":"host=db.example sslmode=verify-full sslrootcert=system"},
                        {"DATABASE_URL":"host=db.example sslmode=verify-full channel_binding=require"},
                        {"PROXY_MODE":"railway", "TRUST_PROXY":"0"}):
            with self.assertRaises(RuntimeError):
                settings({**base, **changes})
        configured = settings({**base, "PROXY_MODE":"railway", "TRUST_PROXY":"1"})
        self.assertTrue(configured["SESSION_COOKIE_SECURE"])
        self.assertTrue(configured["STAGING"])

    def test_container_has_explicit_ca_bundle_and_postgresql_18_clients(self):
        root = Path(__file__).resolve().parent.parent
        dockerfile = (root / "Dockerfile").read_text()
        self.assertIn('SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt"', dockerfile)
        self.assertIn("ca-certificates", dockerfile)
        self.assertIn("postgresql-client-18", dockerfile)
        self.assertIn('PATH="/usr/lib/postgresql/18/bin:$PATH"', dockerfile)
        self.assertNotIn("init-staging", dockerfile)
        self.assertNotIn("create-admin", dockerfile)
        rules = (root / ".dockerignore").read_text().splitlines()
        self.assertEqual(rules[0], "*")
        self.assertFalse(any(rule.startswith("!") and (".env" in rule or "instance" in rule or ".git" in rule)
                             for rule in rules))

    def test_port_binding_preserves_local_default_and_validates_port(self):
        path = Path(__file__).with_name("gunicorn.conf.py")
        with patch.dict(os.environ, {"APP_ENV":"production"}, clear=True):
            self.assertEqual(runpy.run_path(str(path))["bind"], "127.0.0.1:8000")
            os.environ["PORT"] = "8080"
            self.assertEqual(runpy.run_path(str(path))["bind"], "0.0.0.0:8080")
            os.environ["PORT"] = "65536"
            with self.assertRaises(RuntimeError): runpy.run_path(str(path))

    def test_railway_proxy_uses_real_ip_not_client_forwarded_for(self):
        captured = {}
        def app(environ, start_response):
            captured.update(environ)
            return []
        proxy = RailwayProxy(app)
        proxy({"HTTP_X_REAL_IP":"203.0.113.2", "HTTP_X_FORWARDED_FOR":"198.51.100.1",
               "HTTP_X_FORWARDED_PROTO":"https", "REMOTE_ADDR":"127.0.0.1",
               "wsgi.url_scheme":"http"}, MagicMock())
        self.assertEqual(captured["REMOTE_ADDR"], "203.0.113.2")
        self.assertEqual(captured["wsgi.url_scheme"], "https")

    def test_noindex_and_minimal_readiness_with_database_and_media_failures(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(backend.app.config, STAGING=True,
                PROXY_MODE="standard", TEAM_LOGO_DIRECTORY=directory), patch.object(backend, "get_db_connection") as db:
            client = backend.app.test_client()
            response = client.get("/healthz")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {"estado":"disponible"})
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertIn("noindex", response.headers["X-Robots-Tag"])
            self.assertIn("Disallow: /", client.get("/robots.txt").text)
            db.side_effect = RuntimeError("private password")
            response = client.get("/healthz")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("private", response.text)
            db.side_effect = None
            backend.app.config["TEAM_LOGO_DIRECTORY"] = directory + "/missing"
            self.assertEqual(client.get("/healthz").status_code, 503)

    def test_internal_probe_does_not_allow_http_administration_or_untrusted_hosts(self):
        with patch.dict(backend.app.config, STAGING=True, PRODUCTION=True, PROXY_MODE="railway",
                        TRUSTED_HOSTS=["staging.example", "healthcheck.railway.app"]), patch.object(backend, "readiness") as probe:
            probe.return_value = ({"estado":"disponible"}, 200)
            client = backend.app.test_client()
            self.assertEqual(client.get("/healthz", base_url="http://healthcheck.railway.app").status_code, 200)
            probe.assert_called_once()
            for path, origin in (("/admin.html", "http://healthcheck.railway.app"),
                                 ("/healthz", "http://staging.example"),
                                 ("/healthz", "https://evil.example")):
                self.assertEqual(client.get(path, base_url=origin).status_code, 400)

    def test_missing_railway_mount_is_unhealthy_and_probe_hidden_outside_staging(self):
        with patch.dict(backend.app.config, STAGING=True, PROXY_MODE="railway"), patch.dict(os.environ, RAILWAY_VOLUME_MOUNT_PATH="/not-a-mount"), patch.object(backend, "get_db_connection") as db:
            self.assertEqual(backend.app.test_client().get("/healthz").status_code, 503)
            db.assert_not_called()
        with patch.dict(backend.app.config, STAGING=False):
            self.assertEqual(backend.app.test_client().get("/healthz").status_code, 404)

    def test_container_refuses_missing_volume_before_creating_files(self):
        script = runpy.run_path(str(Path(__file__).resolve().parent.parent / "scripts/container_start.py"))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                TEAM_LOGO_DIRECTORY=directory + "/logos", RAILWAY_VOLUME_MOUNT_PATH=directory), patch.object(Path, "is_mount", return_value=False):
            with self.assertRaises(SystemExit): script["main"]()
            self.assertFalse((Path(directory) / "logos").exists())

    def test_container_drops_root_before_executing_server(self):
        script = runpy.run_path(str(Path(__file__).resolve().parent.parent / "scripts/container_start.py"))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                TEAM_LOGO_DIRECTORY=directory + "/logos", RAILWAY_VOLUME_MOUNT_PATH=directory), patch.object(Path, "is_mount", return_value=True), \
                patch("os.getuid", return_value=0), patch("os.chown") as chown, \
                patch("os.setgroups") as groups, patch("os.setgid") as gid, patch("os.setuid") as uid, \
                patch("os.execvp") as execute, patch("sys.argv", ["container_start.py", "gunicorn", "app:app"]):
            calls = MagicMock()
            for name, function in (("groups", groups), ("gid", gid), ("uid", uid), ("execute", execute)):
                calls.attach_mock(function, name)
            script["main"]()
            chown.assert_called_once_with(Path(directory) / "logos", 10001, 10001)
            self.assertEqual([call[0] for call in calls.mock_calls], ["groups", "gid", "uid", "execute"])
            execute.assert_called_once_with("gunicorn", ["gunicorn", "app:app"])

    def test_verification_origin_rejects_credentials_and_non_https(self):
        script = runpy.run_path(str(Path(__file__).resolve().parent.parent / "scripts/verify_staging.py"))
        for origin in ("http://example", "https://user:secret@example", "https://example/?secret=1", "https://example/path"):
            with self.assertRaises(ValueError): script["checked_url"](origin)
        self.assertEqual(script["checked_url"]("https://staging.example/"), "https://staging.example")

    def test_smoke_verification_checks_public_logo_bytes_and_login_logout(self):
        script = runpy.run_path(str(Path(__file__).resolve().parent.parent / "scripts/verify_staging.py"))
        requests = []
        def fetch(req, timeout):
            path = req.full_url.removeprefix("https://staging.example")
            requests.append(path)
            response = MagicMock()
            response.__enter__.return_value = response
            response.status = 200
            response.headers = {"X-Robots-Tag":"noindex", "Content-Security-Policy":"default-src 'self'", "Cache-Control":"no-store"}
            body = b"[]"
            if path == "/robots.txt": body = b"User-agent: *\nDisallow: /"
            if path == "/api/teams": body = b'[{"logo":"/team-logos/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp"}]'
            if path.startswith("/team-logos/"): body = b"logo content"
            if path == "/api/admin/stats": response.status = 401
            if path == "/admin.html" and requests.count(path) == 1:
                response.status = 303
                response.headers["Location"] = "/login"
            if path == "/login":
                body = b'<input name="csrf_token" value="test-csrf">'
                if req.data:
                    response.status = 303
                    response.headers["Set-Cookie"] = "__Host-voli_session=fixture; Secure; HttpOnly; SameSite=Lax"
            if path == "/api/auth/session": body = b'{"csrf_token":"new-token"}'
            if path == "/logout": response.status = 303
            response.read.return_value = body
            return response
        script["verify"].__globals__["build_opener"] = lambda *args: MagicMock(open=fetch)
        with patch("builtins.input", return_value="testadmin"), patch("getpass.getpass", return_value="private"):
            state = script["verify"]("https://staging.example", login=True)
        logo = "/team-logos/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp"
        self.assertEqual(state[logo], hashlib.sha256(b"logo content").hexdigest())
        self.assertIn("/logout", requests)
        self.assertEqual(requests.count("/api/admin/stats"), 2)


class ManagedRestoreTests(unittest.TestCase):
    def test_name_ssl_and_direct_connection_guards_remain_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.bundle(root)
            for database, expected in (("dbname=voleibolcuba sslmode=verify-full", "voleibolcuba"),
                    ("dbname=voli_staging_other sslmode=verify-full", "voli_staging_2026"),
                    ("dbname=voli_staging_2026 sslmode=require", "voli_staging_2026"),
                    ("host=ep-pooler.example dbname=voli_staging_2026 sslmode=verify-full", "voli_staging_2026")):
                with self.subTest(database=database), patch("backup.psycopg.connect") as db:
                    with self.assertRaises(ValueError): restore_empty(root, database, expected)
                    db.assert_not_called()
            with patch("backup.psycopg.connect") as db, patch("backup.run") as restore:
                conn = db.return_value.__enter__.return_value
                conn.info.host = "db.example"
                conn.execute.return_value.fetchone.side_effect = [("voli_staging_2026",), (False,)]
                restore_empty(root, "dbname=voli_staging_2026 sslmode=verify-full", "voli_staging_2026")
                restore.assert_called_once()

    def bundle(self, root, filename=None):
        (root / "database.dump").write_bytes(b"test dump")
        with tarfile.open(root / "logos.tar.gz", "w:gz") as archive:
            item = tarfile.TarInfo(filename or "a" * 32 + ".webp")
            item.size = 4
            archive.addfile(item, io.BytesIO(b"logo"))
        (root / "manifest.json").write_text(json.dumps({name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ("database.dump", "logos.tar.gz")}))

    def test_assets_are_verified_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.bundle(root)
            target = root / "logos"
            restore_media(root, target)
            self.assertEqual((target / ("a" * 32 + ".webp")).read_bytes(), b"logo")
            with patch("backup.psycopg.connect") as db:
                db.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = [("/team-logos/" + "a" * 32 + ".webp",)]
                verify_media(root, target, "dbname=fixture")
                db.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = [("/team-logos/" + "b" * 32 + ".webp",)]
                with self.assertRaises(ValueError): verify_media(root, target, "dbname=fixture")
            with self.assertRaises(ValueError): restore_media(root, target)
            (target / ("a" * 32 + ".webp")).write_bytes(b"corrupt")
            with self.assertRaises(ValueError): verify_media(root, target, "dbname=fixture")
            (root / "database.dump").write_bytes(b"tampered")
            with self.assertRaises(ValueError): verify_bundle(root)

    def test_path_traversal_is_rejected_before_database_connection(self):
        with tempfile.TemporaryDirectory() as temp, patch("backup.psycopg.connect") as db:
            root = Path(temp); self.bundle(root, "../private")
            with self.assertRaises(ValueError): restore_empty(root, "dbname=voli_staging_test sslmode=verify-full", "voli_staging_test")
            db.assert_not_called()

    def test_nonempty_managed_target_is_rejected_without_restore(self):
        with tempfile.TemporaryDirectory() as temp, patch("backup.psycopg.connect") as db, patch("backup.run") as restore:
            root = Path(temp); self.bundle(root)
            conn = db.return_value.__enter__.return_value
            conn.info.host = "db.example"
            conn.execute.return_value.fetchone.side_effect = [("voli_staging_test",), (True,)]
            with self.assertRaises(ValueError): restore_empty(root, "dbname=voli_staging_test sslmode=verify-full", "voli_staging_test")
            restore.assert_not_called()

    def test_managed_restore_is_atomic_and_never_cleans_or_creates(self):
        with tempfile.TemporaryDirectory() as temp, patch("backup.psycopg.connect") as db, patch("backup.run") as restore:
            root = Path(temp); self.bundle(root)
            conn = db.return_value.__enter__.return_value
            conn.info.host = "db.example"
            conn.execute.return_value.fetchone.side_effect = [("voli_staging_test",), (False,)]
            restore_empty(root, "dbname=voli_staging_test sslmode=verify-full", "voli_staging_test")
            command = restore.call_args.args[0]
            self.assertIn("--single-transaction", command)
            self.assertIn("--exit-on-error", command)
            self.assertNotIn("--clean", command)
            self.assertNotIn("--create", command)
