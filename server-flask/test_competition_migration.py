import os
import secrets
import unittest
from pathlib import Path

import psycopg
from psycopg import sql
from werkzeug.security import generate_password_hash


@unittest.skipUnless(os.environ.get("AUTH_TEST_DATABASE_URL"), "PostgreSQL de pruebas no configurado")
class LegacyCompetitionMigrationTests(unittest.TestCase):
    def test_original_records_authentication_and_logos_survive_first_migration(self):
        database = os.environ["AUTH_TEST_DATABASE_URL"]
        schema = "competition_migration_" + secrets.token_hex(8)
        with psycopg.connect(database) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        def cleanup():
            with psycopg.connect(database) as conn:
                conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        self.addCleanup(cleanup)
        migrations = Path(__file__).parent / "migrations"
        with psycopg.connect(database, options=f"-c search_path={schema}") as conn:
            conn.execute("CREATE TABLE teams(id INTEGER PRIMARY KEY,name TEXT UNIQUE NOT NULL,logo_path TEXT)")
            conn.execute("CREATE TABLE jornadas(id INTEGER PRIMARY KEY,number INTEGER UNIQUE NOT NULL)")
            conn.execute("CREATE TABLE matches(id INTEGER PRIMARY KEY,jornada_id INTEGER NOT NULL REFERENCES jornadas(id),team1_id INTEGER NOT NULL REFERENCES teams(id),team2_id INTEGER NOT NULL REFERENCES teams(id),match_time TIME NOT NULL,status TEXT NOT NULL)")
            conn.execute("CREATE TABLE match_sets(match_id INTEGER REFERENCES matches(id) ON DELETE CASCADE,set_number INTEGER,team1_points INTEGER,team2_points INTEGER,PRIMARY KEY(match_id,set_number))")
            conn.execute("INSERT INTO teams VALUES(11,'Uno','original.webp'),(12,'Dos',NULL),(13,'Tres','otro.webp')")
            conn.execute("INSERT INTO jornadas VALUES(21,1),(22,2)")
            conn.execute("INSERT INTO matches VALUES(31,21,11,12,'18:00','finished'),(32,22,11,13,'20:00','scheduled')")
            conn.execute("INSERT INTO match_sets VALUES(31,1,25,10),(31,2,25,10),(31,3,25,10)")
            for migration in ("001_admin_auth.sql","003_scheduling.sql","004_business_rules.sql"):
                conn.execute((migrations / migration).read_text())
            conn.execute("UPDATE matches SET scheduled_at='2026-07-16 00:00:00+00' WHERE id=32")
            conn.execute("INSERT INTO administrators(username,password_hash) VALUES('original',%s)", (generate_password_hash(secrets.token_urlsafe(20)),))
            queries = ["SELECT * FROM teams ORDER BY id", "SELECT id,number FROM jornadas ORDER BY id", "SELECT * FROM matches ORDER BY id", "SELECT * FROM match_sets ORDER BY match_id,set_number", "SELECT * FROM administrators ORDER BY id"]
            before = [conn.execute(query).fetchall() for query in queries]
            for _ in range(2):
                conn.execute((migrations / "005_competitions.sql").read_text())
                self.assertEqual([conn.execute(query).fetchall() for query in queries], before)
            tournament = conn.execute("SELECT id FROM tournaments WHERE is_public").fetchone()[0]
            self.assertEqual(conn.execute("SELECT team_id FROM tournament_teams WHERE tournament_id=%s ORDER BY team_id",(tournament,)).fetchall(), [(11,),(12,),(13,)])
            self.assertEqual(conn.execute("SELECT DISTINCT tournament_id FROM jornadas").fetchall(), [(tournament,)])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM seasons").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0], 1)
            scores = conn.execute("SELECT * FROM match_sets ORDER BY match_id,set_number").fetchall()
            for _ in range(2):
                conn.execute((migrations / "007_match_formats.sql").read_text())
            self.assertEqual(conn.execute("SELECT id,best_of FROM matches ORDER BY id").fetchall(), [(31,5),(32,5)])
            self.assertEqual(conn.execute("SELECT * FROM match_sets ORDER BY match_id,set_number").fetchall(), scores)
