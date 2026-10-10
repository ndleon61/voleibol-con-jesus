import os
import re
import secrets
import unittest
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_hex(32))
import app as backend
import psycopg
from psycopg import sql
from werkzeug.security import generate_password_hash


@unittest.skipUnless(os.environ.get("AUTH_TEST_DATABASE_URL"), "PostgreSQL de pruebas no configurado")
class PostgresSchedulingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = os.environ["AUTH_TEST_DATABASE_URL"]
        cls.schema = "schedule_test_" + secrets.token_hex(8)
        with psycopg.connect(cls.database) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
        cls.addClassCleanup(cls.drop_schema)
        with cls.connect() as conn:
            conn.execute("CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, logo_path TEXT)")
            conn.execute("CREATE TABLE jornadas (id INTEGER PRIMARY KEY, number INTEGER UNIQUE NOT NULL CHECK (number > 0))")
            conn.execute("CREATE TABLE matches (id INTEGER PRIMARY KEY, jornada_id INTEGER NOT NULL REFERENCES jornadas(id), team1_id INTEGER NOT NULL REFERENCES teams(id), team2_id INTEGER NOT NULL REFERENCES teams(id), match_time TIME NOT NULL, status TEXT NOT NULL DEFAULT '', CHECK (team1_id <> team2_id))")
            conn.execute("CREATE TABLE match_sets (match_id INTEGER REFERENCES matches(id) ON DELETE CASCADE, set_number INTEGER, team1_points INTEGER, team2_points INTEGER, PRIMARY KEY (match_id, set_number))")
            conn.execute("INSERT INTO jornadas VALUES (1, 1), (2, 2)")
            conn.execute("INSERT INTO teams VALUES (1, 'Uno', NULL), (2, 'Dos', NULL), (3, 'Tres', NULL)")
            conn.execute("INSERT INTO matches VALUES (1, 1, 1, 2, '18:00', 'finished'), (2, 1, 1, 3, '19:00', '')")
        with patch.object(backend, "get_db_connection", side_effect=cls.connect):
            for command in ("init-auth", "init-scheduling", "init-scheduling", "init-business-rules", "init-business-rules", "init-competitions", "init-competitions", "init-snapshots", "init-match-formats"):
                result = backend.app.test_cli_runner().invoke(args=[command])
                if result.exit_code:
                    raise AssertionError(result.output)
        cls.password = secrets.token_urlsafe(20)
        with cls.connect() as conn:
            conn.execute("INSERT INTO administrators (username, password_hash) VALUES (%s, %s)", ("prueba", generate_password_hash(cls.password)))

    @classmethod
    def connect(cls):
        return psycopg.connect(cls.database, options=f"-c search_path={cls.schema}")

    @classmethod
    def drop_schema(cls):
        with psycopg.connect(cls.database) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    def setUp(self):
        # Reset only this test's isolated fixtures, never the real league tables.
        with self.connect() as conn:
            conn.execute("TRUNCATE match_sets, matches, jornadas, teams, tournament_teams")
            conn.execute("INSERT INTO teams VALUES (1, 'Uno', NULL), (2, 'Dos', NULL), (3, 'Tres', NULL)")
            conn.execute("INSERT INTO tournament_teams SELECT (SELECT id FROM tournaments WHERE legacy_key='original_league'),id FROM teams")
            conn.execute("INSERT INTO jornadas VALUES (1, 1), (2, 2)")
            conn.execute("INSERT INTO matches (id, jornada_id, team1_id, team2_id, match_time, status, best_of) VALUES (1, 1, 1, 2, '18:00', 'finished', 5), (2, 1, 1, 3, '19:00', '', 5)")
            conn.execute("INSERT INTO match_sets VALUES (1, 1, 25, 10), (1, 2, 25, 10), (1, 3, 25, 10)")
            conn.execute("DELETE FROM administrator_login_attempts")
        db_patch = patch.object(backend, "get_db_connection", side_effect=self.connect)
        db_patch.start()
        self.addCleanup(db_patch.stop)
        self.client = backend.app.test_client()
        page = self.client.get("/login")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
        response = self.client.post("/login", data={"username":"prueba", "password":self.password, "csrf_token":token})
        self.assertEqual(response.status_code, 303)
        self.headers = {"X-CSRF-Token":self.client.get("/api/auth/session").json["csrf_token"]}

    def request(self, method, path, data=None):
        return self.client.open(path, method=method, json=data, headers=self.headers)

    def match(self, **changes):
        return {"team1Id":1, "team2Id":2, "date":"2026-07-15", "time":"20:00", **changes}

    def test_create_edit_delete_empty_jornada(self):
        created = self.request("POST", "/api/admin/jornadas", {"number":3})
        self.assertEqual(created.status_code, 201)
        id = created.json["jornada"]["id"]
        self.assertGreater(id, 2)
        self.assertEqual(self.request("PUT", f"/api/admin/jornadas/{id}", {"number":4}).status_code, 200)
        self.assertEqual(self.request("DELETE", f"/api/admin/jornadas/{id}").status_code, 200)
        self.assertEqual(len(self.client.get("/api/jornadas").json), 2)

    def test_duplicate_invalid_and_missing_jornadas(self):
        for data in ({}, {"number":0}, {"number":True}, {"number":1.5}):
            self.assertEqual(self.request("POST", "/api/admin/jornadas", data).status_code, 400)
        self.assertEqual(self.request("POST", "/api/admin/jornadas", {"number":1}).status_code, 409)
        self.assertEqual(self.request("PUT", "/api/admin/jornadas/2", {"number":1}).status_code, 409)
        self.assertEqual(self.request("PUT", "/api/admin/jornadas/999", {"number":9}).status_code, 404)
        self.assertEqual(self.request("DELETE", "/api/admin/jornadas/999").status_code, 404)

    def test_three_set_default_corrections_and_history(self):
        id = self.request("POST", "/api/admin/jornadas/2/matches", self.match()).json["matchId"]
        self.assertEqual(self.client.get("/api/jornadas").json[1]["games"][0]["bestOf"], 3)
        scores = [{"team1Points":25,"team2Points":10}] * 2
        self.assertEqual(self.request("PUT", f"/api/admin/matches/{id}/result", {"sets":scores}).status_code, 200)
        before = self.client.get("/api/jornadas").json
        self.assertEqual(self.request("PUT", f"/api/admin/matches/{id}/result", {"sets":scores * 2}).status_code, 400)
        self.assertEqual(self.client.get("/api/jornadas").json, before)
        self.assertEqual(self.request("PUT", f"/api/admin/matches/{id}", self.match(bestOf=5)).status_code, 409)
        reverse = [{"team1Points":10,"team2Points":25}] * 2
        for _ in range(2):
            self.assertEqual(self.request("PUT", f"/api/admin/matches/{id}/result", {"sets":reverse}).status_code, 200)
        table = {row["team"]:row for row in self.client.get("/api/standings").json}
        self.assertEqual((table["Uno"]["wins"],table["Uno"]["losses"],table["Uno"]["setsWon"],table["Uno"]["setsLost"]), (1,1,3,2))
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM match_sets WHERE match_id=%s",(id,)).fetchone()[0], 2)
        with self.assertRaises(psycopg.errors.CheckViolation), self.connect() as conn:
            conn.execute("UPDATE matches SET best_of=5 WHERE id=%s", (id,))

    def test_final_format_validation_and_pending_edit(self):
        for format in (4, True, "3", None):
            self.assertEqual(self.request("POST", "/api/admin/jornadas/2/matches", self.match(bestOf=format)).status_code, 400)
        id = self.request("POST", "/api/admin/jornadas/2/matches", self.match(bestOf=5)).json["matchId"]
        self.assertEqual(self.request("PUT", f"/api/admin/matches/{id}", self.match()).status_code, 200)
        self.assertEqual(self.client.get("/api/admin/jornadas").json[1]["games"][0]["bestOf"], 5)
        for format in (3, 5):
            self.assertEqual(self.request("PUT", f"/api/admin/matches/{id}", self.match(bestOf=format)).status_code, 200)
        scores = [{"team1Points":25,"team2Points":0},{"team1Points":0,"team2Points":25}] * 2 + [{"team1Points":15,"team2Points":13}]
        self.assertEqual(self.request("PUT", f"/api/admin/matches/{id}/result", {"sets":scores[:2]}).status_code, 400)
        self.assertEqual(self.request("PUT", f"/api/admin/matches/{id}/result", {"sets":scores}).status_code, 200)

    def test_format_migration_preserves_existing_results(self):
        before = self.client.get("/api/jornadas").json
        for _ in range(2):
            result = backend.app.test_cli_runner().invoke(args=["init-match-formats"])
            self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.client.get("/api/jornadas").json, before)
        self.assertEqual(before[0]["games"][0]["bestOf"], 5)

    def test_nonempty_jornada_cannot_be_deleted(self):
        self.assertEqual(self.request("DELETE", "/api/admin/jornadas/1").status_code, 409)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM match_sets").fetchone()[0], 3)
        self.assertEqual(self.request("PUT", "/api/admin/jornadas/1", {"number":5}).status_code, 200)
        self.assertEqual(self.client.get("/api/jornadas").json[-1]["number"], 5)

    def test_create_reschedule_and_delete_match_public_calendar(self):
        created = self.request("POST", "/api/admin/jornadas/2/matches", self.match())
        self.assertEqual(created.status_code, 201, created.text)
        id = created.json["matchId"]
        public = self.client.get("/api/jornadas").json[1]["games"][0]
        self.assertEqual((public["id"], public["date"], public["time"], public["status"]), (id, "2026-07-15", "20:00", "scheduled"))
        self.assertEqual(public["startsAt"], "2026-07-16T00:00:00+00:00")
        self.assertEqual(self.request("PUT", f"/api/admin/matches/{id}", self.match(team2Id=3, date="2026-01-15", time="18:00")).status_code, 200)
        updated = self.client.get("/api/jornadas").json[1]["games"][0]
        self.assertEqual((updated["team2"], updated["startsAt"]), ("Tres", "2026-01-15T23:00:00+00:00"))
        self.assertEqual(self.request("DELETE", f"/api/admin/matches/{id}").status_code, 200)
        self.assertEqual(self.client.get("/api/jornadas").json[1]["games"], [])

    def test_invalid_teams_dates_and_parent(self):
        for changes in ({"team2Id":1}, {"team2Id":999}, {"team1Id":True}, {"date":"2026-02-30"}, {"time":"24:00"}, {"date":"2026-03-08", "time":"00:30"}):
            self.assertEqual(self.request("POST", "/api/admin/jornadas/2/matches", self.match(**changes)).status_code, 400)
        self.assertEqual(self.request("POST", "/api/admin/jornadas/999/matches", self.match()).status_code, 404)
        self.assertEqual(self.request("PUT", "/api/admin/matches/999", self.match()).status_code, 404)
        self.assertEqual(self.request("DELETE", "/api/admin/matches/999").status_code, 404)

    def test_duplicate_matches_reverse_order_and_legacy_time(self):
        self.assertEqual(self.request("POST", "/api/admin/jornadas/2/matches", self.match()).status_code, 201)
        self.assertEqual(self.request("POST", "/api/admin/jornadas/2/matches", self.match(team1Id=2, team2Id=1)).status_code, 409)
        self.assertEqual(self.request("POST", "/api/admin/jornadas/1/matches", self.match(time="18:00")).status_code, 409)
        second = self.request("POST", "/api/admin/jornadas/2/matches", self.match(time="22:00")).json["matchId"]
        self.assertEqual(self.request("PUT", f"/api/admin/matches/{second}", self.match()).status_code, 409)

    def test_completed_results_protected_but_time_can_be_corrected(self):
        before = self.client.get("/api/standings").json
        self.assertEqual(self.request("PUT", "/api/admin/matches/1", self.match(team1Id=2, team2Id=1)).status_code, 409)
        self.assertEqual(self.request("DELETE", "/api/admin/matches/1").status_code, 409)
        self.assertEqual(self.request("PUT", "/api/admin/matches/1", self.match(time="21:00")).status_code, 200)
        self.assertEqual(self.client.get("/api/standings").json, before)
        public = self.client.get("/api/jornadas").json[0]["games"][0]
        self.assertEqual(public["status"], "finished")
        self.assertEqual(len(public["results"]["sets"]), 3)

    def test_partial_results_are_also_protected(self):
        with self.connect() as conn:
            conn.execute("INSERT INTO match_sets VALUES (2, 1, 25, 10)")
        self.assertEqual(self.request("DELETE", "/api/admin/matches/2").status_code, 409)
        self.assertEqual(self.request("PUT", "/api/admin/matches/2", self.match()).status_code, 409)

    def test_authentication_and_csrf_all_modifications(self):
        guest = backend.app.test_client()
        paths = [("POST","/api/admin/jornadas"), ("PUT","/api/admin/jornadas/1"), ("DELETE","/api/admin/jornadas/1"), ("POST","/api/admin/jornadas/1/matches"), ("PUT","/api/admin/matches/1"), ("DELETE","/api/admin/matches/1")]
        for method, path in paths:
            self.assertEqual(guest.open(path, method=method, json={}).status_code, 401)
            self.assertEqual(self.client.open(path, method=method, json={}).status_code, 403)
        self.assertEqual(guest.get("/api/admin/jornadas").status_code, 401)
        self.assertEqual(guest.get("/api/jornadas").status_code, 200)

    def test_migration_keeps_unknown_historical_dates_and_ids(self):
        result = backend.app.test_cli_runner().invoke(args=["init-scheduling"])
        self.assertEqual(result.exit_code, 0, result.output)
        with self.connect() as conn:
            rows = conn.execute("SELECT id, scheduled_at FROM matches ORDER BY id").fetchall()
            self.assertEqual(rows, [(1, None), (2, None)])
        data = self.client.get("/api/admin/jornadas").json
        self.assertTrue(data[0]["games"][0]["hasResults"])
        self.assertEqual(data[0]["games"][1]["time"], "19:00")

    def test_overlapping_slots_global_and_back_to_back(self):
        self.assertEqual(self.request("POST", "/api/admin/jornadas/2/matches", self.match()).status_code, 201)
        with self.connect() as conn:
            conn.execute("INSERT INTO jornadas (id, number) VALUES (99, 99)")
        for jornada, changes in ((2, {"team2Id":3,"time":"21:59"}), (99, {"team1Id":3,"team2Id":1,"time":"19:00"})):
            conflict = self.request("POST", f"/api/admin/jornadas/{jornada}/matches", self.match(**changes))
            self.assertEqual(conflict.status_code, 409)
            self.assertIn("solapa", conflict.json["error"])
        self.assertEqual(self.request("POST", "/api/admin/jornadas/2/matches", self.match(team2Id=3,time="22:00")).status_code, 201)
        self.assertEqual(self.request("POST", "/api/admin/jornadas/99/matches", self.match()).status_code, 409)

    def test_cross_midnight_slots_and_legacy_same_jornada(self):
        self.assertEqual(self.request("POST", "/api/admin/jornadas/2/matches", self.match(time="23:30")).status_code, 201)
        self.assertEqual(self.request("POST", "/api/admin/jornadas/2/matches", self.match(team2Id=3,date="2026-07-16",time="00:30")).status_code, 409)
        self.assertEqual(self.request("POST", "/api/admin/jornadas/2/matches", self.match(team2Id=3,date="2026-07-16",time="01:30")).status_code, 201)
        self.assertEqual(self.request("POST", "/api/admin/jornadas/1/matches", self.match(time="18:30")).status_code, 409)

    def test_duration_validation_preservation_and_jornada_assignment(self):
        for duration in (0, -1, True, 1.5, 1441, None):
            self.assertEqual(self.request("POST", "/api/admin/jornadas/2/matches", self.match(durationMinutes=duration)).status_code, 400)
        self.assertEqual(self.request("POST", "/api/admin/jornadas/2/matches", self.match(jornadaId=1)).status_code, 400)
        result = self.request("POST", "/api/admin/jornadas/2/matches", self.match(durationMinutes=30))
        id = result.json["matchId"]
        self.assertEqual(self.request("PUT", f"/api/admin/matches/{id}", self.match(time="19:00")).status_code, 200)
        self.assertEqual(self.request("PUT", f"/api/admin/matches/{id}", self.match(jornadaId=1)).status_code, 400)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT duration_minutes FROM matches WHERE id = %s", (id,)).fetchone()[0], 30)
        self.assertEqual(self.request("POST", "/api/admin/jornadas/2/matches", self.match(time="19:30")).status_code, 201)

    def test_rescheduling_into_conflict_rolls_back(self):
        first = self.request("POST", "/api/admin/jornadas/2/matches", self.match()).json["matchId"]
        second = self.request("POST", "/api/admin/jornadas/2/matches", self.match(team2Id=3,time="22:00")).json["matchId"]
        self.assertEqual(self.request("PUT", f"/api/admin/matches/{second}", self.match(team2Id=3,time="21:00")).status_code, 409)
        data = self.client.get("/api/admin/jornadas").json[1]["games"]
        self.assertEqual([(m["id"],m["time"]) for m in data], [(first,"20:00"),(second,"22:00")])

    def test_result_corrections_update_standings_without_duplicate_sets(self):
        sets = [{"team1Points":0,"team2Points":25}] * 3
        for _ in range(2):
            self.assertEqual(self.request("PUT", "/api/admin/matches/1/result", {"sets":sets}).status_code, 200)
        table = {row["team"]:row for row in self.client.get("/api/standings").json}
        self.assertEqual(table["Uno"], {"team":"Uno","teamId":1,"logo":"","wins":0,"losses":1,"setsWon":0,"setsLost":3})
        self.assertEqual(table["Dos"], {"team":"Dos","teamId":2,"logo":"","wins":1,"losses":0,"setsWon":3,"setsLost":0})
        before = self.client.get("/api/jornadas").json
        self.assertEqual(self.request("PUT", "/api/admin/matches/1/result", {"sets":[{"team1Points":26,"team2Points":0}]*3}).status_code, 400)
        self.assertEqual(self.client.get("/api/jornadas").json, before)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM match_sets WHERE match_id = 1").fetchone()[0], 3)
        five = [{"team1Points":25,"team2Points":0},{"team1Points":0,"team2Points":25}]*2 + [{"team1Points":15,"team2Points":0}]
        self.assertEqual(self.request("PUT", "/api/admin/matches/1/result", {"sets":five}).status_code, 200)
        self.assertEqual(self.request("PUT", "/api/admin/matches/1/result", {"sets":sets}).status_code, 200)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT set_number FROM match_sets WHERE match_id = 1 ORDER BY set_number").fetchall(), [(1,),(2,),(3,)])

    def test_all_shared_scores_through_authenticated_result_api(self):
        fixtures = json.loads((Path(__file__).parent.parent / "tests/business-rules.json").read_text())
        for fixture in fixtures["scores"]:
            with self.subTest(fixture["name"]):
                sets = [{"team1Points": p1,"team2Points": p2} for p1,p2 in fixture["sets"]]
                if "numbers" in fixture:
                    for item, number in zip(sets, fixture["numbers"]):
                        item["setNumber"] = number
                before = self.client.get("/api/jornadas").json
                response = self.request("PUT", "/api/admin/matches/1/result", {"sets":sets})
                self.assertEqual(response.status_code, 200 if fixture["valid"] else 400)
                if not fixture["valid"]:
                    self.assertIn("error", response.json)
                    self.assertEqual(self.client.get("/api/jornadas").json, before)

    def test_result_failure_rolls_back_without_leaking_internal_error(self):
        with self.connect() as conn:
            conn.execute("CREATE FUNCTION reject_test_score() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'secret_internal_test_detail'; END $$")
            conn.execute("CREATE TRIGGER reject_test_score BEFORE INSERT ON match_sets FOR EACH ROW WHEN (NEW.set_number = 2) EXECUTE FUNCTION reject_test_score()")
        def cleanup():
            with self.connect() as conn:
                conn.execute("DROP TRIGGER reject_test_score ON match_sets")
                conn.execute("DROP FUNCTION reject_test_score()")
        self.addCleanup(cleanup)
        before = self.client.get("/api/jornadas").json
        with self.assertLogs(backend.app.logger, level="ERROR"):
            response = self.request("PUT", "/api/admin/matches/1/result", {"sets":[{"team1Points":0,"team2Points":25}]*3})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret_internal_test_detail", response.text)
        self.assertEqual(self.client.get("/api/jornadas").json, before)

    def test_database_constraints_and_history_guards(self):
        statements = [
            "DELETE FROM matches WHERE id = 1",
            "UPDATE matches SET team2_id = 3 WHERE id = 1",
            "UPDATE matches SET jornada_id = 2 WHERE id = 1",
            "UPDATE matches SET status = 'scheduled' WHERE id = 1",
            "DELETE FROM teams WHERE id = 1",
            "DELETE FROM jornadas WHERE id = 1",
            "INSERT INTO match_sets VALUES (2, 6, 25, 0)",
            "INSERT INTO match_sets VALUES (2, 1, -1, 25)",
            "INSERT INTO match_sets VALUES (2, 1, 25, 25)",
            "UPDATE matches SET duration_minutes = 0 WHERE id = 2",
            "INSERT INTO matches (jornada_id, team1_id, team2_id, match_time) VALUES (2, 1, 1, '20:00')",
        ]
        for statement in statements:
            with self.subTest(statement), self.assertRaises(psycopg.IntegrityError):
                with self.connect() as conn:
                    conn.execute(statement)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM match_sets WHERE match_id = 1").fetchone()[0], 3)

    def concurrent_requests(self, requests):
        barrier = Barrier(2)
        cookie = self.client.get_cookie("voli_session").value
        def worker(item):
            client = backend.app.test_client()
            client.set_cookie("voli_session", cookie)
            barrier.wait(timeout=10)
            method, path, data = item
            return client.open(path, method=method, json=data, headers=self.headers).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, item) for item in requests]
            return [future.result(timeout=15) for future in futures]

    def test_concurrent_conflicting_schedule_writers(self):
        statuses = self.concurrent_requests([
            ("POST","/api/admin/jornadas/2/matches",self.match()),
            ("POST","/api/admin/jornadas/2/matches",self.match(team2Id=3,time="20:30")),
        ])
        self.assertEqual(sorted(statuses), [201,409])
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM matches WHERE jornada_id = 2").fetchone()[0], 1)

    def test_concurrent_result_corrections_are_atomic(self):
        statuses = self.concurrent_requests([
            ("PUT","/api/admin/matches/1/result",{"sets":[{"team1Points":25,"team2Points":0}]*3}),
            ("PUT","/api/admin/matches/1/result",{"sets":[{"team1Points":0,"team2Points":25}]*3}),
        ])
        self.assertEqual(statuses, [200,200])
        with self.connect() as conn:
            rows = conn.execute("SELECT set_number, team1_points, team2_points FROM match_sets WHERE match_id = 1 ORDER BY set_number").fetchall()
        self.assertIn(rows, [[(n,25,0) for n in (1,2,3)],[(n,0,25) for n in (1,2,3)]])
