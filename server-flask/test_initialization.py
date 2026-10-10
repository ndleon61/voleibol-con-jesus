import os
import secrets
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from PIL import Image

os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_hex(32))
import app as backend


class InitializationSafetyTests(unittest.TestCase):
    def test_confirmation_and_explicit_staging_target_required_before_connection(self):
        runner = backend.app.test_cli_runner()
        with patch.object(backend, "get_db_connection") as connect:
            result = runner.invoke(args=["init-staging", "--database-name", "voli_staging_2026"])
            self.assertNotEqual(result.exit_code, 0)
            for database in ("dbname=voleibolcuba sslmode=verify-full",
                             "dbname=voli_staging_2026 sslmode=require",
                             "dbname=voli_staging_2026 host=example-pooler sslmode=verify-full"):
                with patch.dict(os.environ, DATABASE_URL=database):
                    result = runner.invoke(args=["init-staging", "--database-name",
                                                 "voli_staging_2026", "--empty-database-confirmed"])
                    self.assertNotEqual(result.exit_code, 0)
            connect.assert_not_called()


@unittest.skipUnless(os.environ.get("AUTH_TEST_DATABASE_URL"), "PostgreSQL de pruebas no configurado")
class FreshInstallationTests(unittest.TestCase):
    def setUp(self):
        source = os.environ["AUTH_TEST_DATABASE_URL"]
        with psycopg.connect(source) as conn:
            if conn.info.server_version < 180006 or conn.info.server_version >= 190000:
                self.skipTest("La instalación staging requiere pruebas aisladas PostgreSQL 18.6")
        self.name = "voli_staging_fresh_" + secrets.token_hex(8)
        self.database = make_conninfo(source, dbname=self.name, sslmode="verify-full")
        self.control = make_conninfo(source, dbname="postgres")
        with psycopg.connect(self.control, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(self.name)))
        self.addCleanup(self.drop_database)
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        media_patch = patch.dict(backend.app.config, TEAM_LOGO_DIRECTORY=self.media.name)
        media_patch.start()
        self.addCleanup(media_patch.stop)
        connection_patch = patch.object(backend, "get_db_connection", side_effect=self.connect)
        connection_patch.start()
        self.addCleanup(connection_patch.stop)

    def connect(self):
        return psycopg.connect(self.database)

    def drop_database(self):
        with psycopg.connect(self.control, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(self.name)))

    def initialize(self):
        with patch.dict(os.environ, DATABASE_URL=self.database):
            return backend.app.test_cli_runner().invoke(args=["init-staging", "--database-name",
                                                              self.name, "--empty-database-confirmed"])

    def test_atomic_failure_and_rejection_of_nonempty_database(self):
        with patch("initialization.apply_snapshots", side_effect=psycopg.OperationalError("private")):
            failed = self.initialize()
        self.assertNotEqual(failed.exit_code, 0)
        self.assertNotIn("private", failed.output)
        with self.connect() as conn:
            self.assertIsNone(conn.execute("SELECT to_regclass('teams')").fetchone()[0])
            conn.execute("CREATE TABLE sentinel (value TEXT)")
            conn.execute("INSERT INTO sentinel VALUES ('preservado')")
        rejected = self.initialize()
        self.assertNotEqual(rejected.exit_code, 0)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT value FROM sentinel").fetchone()[0], "preservado")

    def test_fresh_authenticated_league_workflow_and_historical_snapshots(self):
        result = self.initialize()
        self.assertEqual(result.exit_code, 0, result.output)
        with self.connect() as conn:
            for table in ("teams", "seasons", "tournaments", "jornadas", "matches", "match_sets", "administrators"):
                self.assertEqual(conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM pg_constraint WHERE connamespace='public'::regnamespace AND NOT convalidated").fetchone()[0], 0)
        password = secrets.token_urlsafe(24)
        created = backend.app.test_cli_runner().invoke(args=["create-admin", "--username", "staging_prueba"],
                                                      input=password + "\n" + password + "\n")
        self.assertEqual(created.exit_code, 0, created.output)
        client = backend.app.test_client()
        for path in ("/api/seasons", "/api/tournaments", "/api/teams", "/api/jornadas", "/api/standings"):
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json, [])
        self.assertEqual(client.get("/api/admin/teams").status_code, 401)
        client.get("/login").close()
        with client.session_transaction() as session:
            token = session["csrf_token"]
        login = client.post("/login", data={"username": "staging_prueba", "password": password, "csrf_token": token})
        self.assertEqual(login.status_code, 303)
        headers = {"X-CSRF-Token": client.get("/api/auth/session").json["csrf_token"]}

        def api(method, path, data, status=201):
            response = client.open(path, method=method, json=data, headers=headers)
            self.assertEqual(response.status_code, status, response.text)
            return response.json

        season = api("POST", "/api/admin/seasons", {"name": "Temporada de pruebas", "status": "active"})["season"]["id"]
        tournament = api("POST", "/api/admin/tournaments", {"seasonId": season, "name": "Torneo de pruebas", "status": "active"})["tournament"]["id"]
        api("POST", f"/api/admin/tournaments/{tournament}/activate", {}, 200)
        logo = BytesIO()
        Image.new("RGB", (16, 16), "red").save(logo, format="PNG")
        logo.seek(0)
        team = client.post("/api/admin/teams", data={"name": "Equipo Uno", "logo": (logo, "logo.png")}, headers=headers)
        self.assertEqual(team.status_code, 201, team.text)
        first = team.json["team"]
        second = api("POST", "/api/admin/teams", {"name": "Equipo Dos"})["team"]
        for item in (first, second):
            api("POST", f"/api/admin/tournaments/{tournament}/teams", {"teamId": item["id"]})
        scope = f"?tournament_id={tournament}"
        jornada = api("POST", "/api/admin/jornadas" + scope, {"number": 1})["jornada"]["id"]
        match = api("POST", f"/api/admin/jornadas/{jornada}/matches" + scope,
                    {"team1Id": first["id"], "team2Id": second["id"], "date": "2026-10-10", "time": "18:00"})["matchId"]
        api("PUT", f"/api/admin/matches/{match}/result" + scope,
            {"sets": [{"team1Points": 25, "team2Points": 10}] * 2}, 200)
        standings = client.get(f"/api/tournaments/{tournament}/standings").json
        self.assertEqual((standings[0]["wins"], standings[0]["setsWon"], standings[1]["losses"]), (1, 2, 1))
        api("PUT", f"/api/admin/tournaments/{tournament}", {"status": "completed"}, 200)
        api("PUT", f"/api/admin/teams/{first['id']}", {"name": "Nombre nuevo", "remove_logo": True}, 200)
        historical = client.get(f"/api/tournaments/{tournament}/teams").json
        self.assertEqual(historical[0]["name"], "Equipo Uno")
        self.assertEqual(historical[0]["logo"], first["logo"])
        client.get(first["logo"]).close()
        api("PUT", f"/api/admin/tournaments/{tournament}", {"status": "archived"}, 200)
        api("PUT", f"/api/admin/matches/{match}/result" + scope,
            {"sets": [{"team1Points": 25, "team2Points": 12}] * 3}, 409)
        self.assertNotEqual(self.initialize().exit_code, 0)
