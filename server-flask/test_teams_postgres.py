import os
import re
import secrets
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_hex(32))
import app as backend
import psycopg
from psycopg import sql
from werkzeug.security import generate_password_hash


@unittest.skipUnless(os.environ.get("AUTH_TEST_DATABASE_URL"), "PostgreSQL de pruebas no configurado")
class PostgresTeamTests(unittest.TestCase):
    def test_migration_crud_and_history(self):
        database = os.environ["AUTH_TEST_DATABASE_URL"]
        schema = "teams_test_" + secrets.token_hex(8)
        with psycopg.connect(database) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

        def connect():
            return psycopg.connect(database, options=f"-c search_path={schema}")

        try:
            with connect() as conn:
                conn.execute("CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, logo_path TEXT)")
                conn.execute("CREATE TABLE jornadas (id INTEGER PRIMARY KEY, number INTEGER UNIQUE NOT NULL)")
                conn.execute("CREATE TABLE matches (id INTEGER PRIMARY KEY, team1_id INTEGER REFERENCES teams(id), team2_id INTEGER REFERENCES teams(id), jornada_id INTEGER REFERENCES jornadas(id), match_time TIME, status TEXT DEFAULT '')")
                conn.execute("CREATE TABLE match_sets (match_id INTEGER REFERENCES matches(id), set_number INTEGER, team1_points INTEGER, team2_points INTEGER)")
                conn.execute("INSERT INTO teams (id, name) VALUES (1, 'Los Lobos'), (2, 'Los Abusadores')")
                conn.execute("INSERT INTO jornadas VALUES (1,1)")
                conn.execute("INSERT INTO matches VALUES (1, 1, 2, 1, '18:00', '')")
                conn.execute("INSERT INTO match_sets VALUES (1, 1, 25, 10)")
            with tempfile.TemporaryDirectory() as logos, patch.dict(backend.app.config, TEAM_LOGO_DIRECTORY=logos), patch.object(backend, "get_db_connection", side_effect=connect):
                runner = backend.app.test_cli_runner()
                for command in ("init-auth", "init-teams", "init-teams", "init-scheduling", "init-business-rules", "init-competitions", "init-snapshots", "init-match-formats"):
                    result = runner.invoke(args=[command])
                    self.assertEqual(result.exit_code, 0, result.output)
                password = secrets.token_urlsafe(20)
                with connect() as conn:
                    conn.execute("INSERT INTO administrators (username, password_hash) VALUES (%s, %s)", ("prueba", generate_password_hash(password)))
                client = backend.app.test_client()
                self.assertEqual(client.get("/api/teams").status_code, 200)
                self.assertEqual(client.post("/api/admin/teams", json={"name": "Nuevo"}).status_code, 401)
                page = client.get("/login")
                csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
                self.assertEqual(client.post("/login", data={"username": "prueba", "password": password, "csrf_token": csrf}).status_code, 303)
                headers = {"X-CSRF-Token": client.get("/api/auth/session").json["csrf_token"]}
                self.assertEqual(client.post("/api/admin/teams", json={"name": "Nuevo"}).status_code, 403)
                created = client.post("/api/admin/teams", json={"name": "Nuevo"}, headers=headers)
                self.assertEqual(created.status_code, 201, created.text)
                team_id = created.json["team"]["id"]
                self.assertGreater(team_id, 2)
                self.assertEqual(client.post("/api/admin/teams", json={"name": " nuevo "}, headers=headers).status_code, 409)
                self.assertEqual(client.put("/api/admin/teams/1", json={"name": "Lobos renovados", "remove_logo": True}, headers=headers).status_code, 200)
                self.assertEqual(runner.invoke(args=["init-teams"]).exit_code, 0)
                self.assertEqual(client.delete("/api/admin/teams/1", headers=headers).status_code, 409)
                self.assertEqual(client.delete(f"/api/admin/teams/{team_id}", headers=headers).status_code, 200)
                with connect() as conn:
                    self.assertEqual(conn.execute("SELECT id, name, logo_path FROM teams WHERE id = 1").fetchone(), (1, "Lobos renovados", None))
                    self.assertEqual(conn.execute("SELECT id,team1_id,team2_id FROM matches").fetchall(), [(1, 1, 2)])
                    self.assertEqual(conn.execute("SELECT * FROM match_sets").fetchall(), [(1, 1, 25, 10)])
        finally:
            # Only this test's isolated schema is removed, never league tables.
            with psycopg.connect(database) as conn:
                conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
