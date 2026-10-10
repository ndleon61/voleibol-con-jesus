import os
import secrets
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_hex(32))
import app as backend
import test_scheduling_postgres as scheduling_tests


@unittest.skipUnless(os.environ.get("AUTH_TEST_DATABASE_URL"), "PostgreSQL de pruebas no configurado")
class CompetitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scheduling_tests.PostgresSchedulingTests.setUpClass()
        cls.addClassCleanup(scheduling_tests.PostgresSchedulingTests.doClassCleanups)

    def connect(self):
        return scheduling_tests.PostgresSchedulingTests.connect()

    def setUp(self):
        # Only this suite's isolated schema is reset, never application records.
        with self.connect() as conn:
            conn.execute("TRUNCATE match_sets,matches,jornadas,teams,tournament_teams,tournaments,seasons RESTART IDENTITY")
            season = conn.execute("INSERT INTO seasons(name,status,legacy_key) VALUES('Temporada original','active','original_league') RETURNING id").fetchone()[0]
            conn.execute("INSERT INTO tournaments(season_id,name,status,is_public,legacy_key) VALUES(%s,'Torneo original','active',TRUE,'original_league')",(season,))
        fixture = scheduling_tests.PostgresSchedulingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.client,self.headers = fixture.client,fixture.headers
        with self.connect() as conn:
            for table,maximum in (("teams",3),("jornadas",2),("matches",2)):
                conn.execute("SELECT setval(pg_get_serial_sequence(%s,'id'),%s,TRUE)",(table,maximum))

    def api(self,method,path,data=None,tournament=None):
        if tournament is not None:
            path+=f"?tournament_id={tournament}"
        return self.client.open(path,method=method,json=data,headers=self.headers)

    def tournament(self,name="Otro torneo",season=1,**fields):
        response=self.api("POST","/api/admin/tournaments",{"seasonId":season,"name":name,**fields})
        self.assertEqual(response.status_code,201,response.text)
        return response.json["tournament"]["id"]

    def enroll(self,tournament,teams=(1,2)):
        for team in teams:
            self.assertEqual(self.api("POST",f"/api/admin/tournaments/{tournament}/teams",{"teamId":team}).status_code,201)

    def jornada(self,tournament,number=1):
        response=self.api("POST","/api/admin/jornadas",{"number":number},tournament)
        self.assertEqual(response.status_code,201,response.text)
        return response.json["jornada"]["id"]

    def match(self,tournament,jornada,**fields):
        return self.api("POST",f"/api/admin/jornadas/{jornada}/matches",{"team1Id":1,"team2Id":2,"date":"2026-07-15","time":"20:00","bestOf":5,**fields},tournament)

    def test_seasons_create_update_dates_names_and_transitions(self):
        r=self.api("POST","/api/admin/seasons",{"name":"  Temporada  2026 ","startDate":"2026-01-01","endDate":"2026-12-31"})
        self.assertEqual(r.status_code,201)
        id=r.json["season"]["id"]
        self.assertEqual(r.json["season"]["name"],"Temporada 2026")
        self.assertEqual(self.api("POST","/api/admin/seasons",{"name":"temporada 2026"}).status_code,409)
        self.assertEqual(self.api("PUT",f"/api/admin/seasons/{id}",{"status":"active"}).status_code,200)
        self.assertEqual(self.api("PUT",f"/api/admin/seasons/{id}",{"status":"planned"}).status_code,409)
        for data in ({"name":""},{"name":"A"*101},{"name":"Uno","status":"invalid"},{"name":"Uno","startDate":"2026-02-30"},{"name":"Uno","startDate":"2026-12-31","endDate":"2026-01-01"}):
            self.assertEqual(self.api("POST","/api/admin/seasons",data).status_code,400)

    def test_best_of_three_tournament_completion(self):
        tournament = self.tournament()
        self.enroll(tournament)
        jornada = self.jornada(tournament)
        match = self.match(tournament,jornada,bestOf=3).json["matchId"]
        scores = [{"team1Points":25,"team2Points":0},{"team1Points":0,"team2Points":25},{"team1Points":25,"team2Points":20}]
        self.assertEqual(self.api("PUT",f"/api/admin/matches/{match}/result",{"sets":scores},tournament).status_code,200)
        standings = self.api("GET",f"/api/tournaments/{tournament}/standings").json
        self.assertEqual((standings[0]["wins"],standings[0]["setsWon"],standings[0]["setsLost"]),(1,2,1))
        self.assertEqual(self.api("PUT",f"/api/admin/tournaments/{tournament}",{"status":"completed"}).status_code,200)
        self.assertEqual(self.api("GET",f"/api/tournaments/{tournament}/standings").json,standings)

    def test_tournaments_season_dates_and_name_uniqueness(self):
        s=self.api("POST","/api/admin/seasons",{"name":"2026","startDate":"2026-01-01","endDate":"2026-12-31"}).json["season"]["id"]
        id=self.tournament(season=s,startDate="2026-01-01",endDate="2026-12-31")
        self.assertEqual(self.api("POST",f"/api/admin/seasons/{s}/tournaments",{"name":"otro torneo","startDate":"2026-01-01","endDate":"2026-12-31"}).status_code,409)
        self.assertEqual(self.api("POST","/api/admin/tournaments",{"seasonId":s,"name":"Fuera","startDate":"2025-01-01","endDate":"2026-12-31"}).status_code,400)
        self.assertEqual(self.api("PUT",f"/api/admin/tournaments/{id}",{"seasonId":1}).status_code,409)
        self.assertEqual(len(self.api("GET",f"/api/admin/seasons/{s}/tournaments").json),1)
        self.assertEqual(self.api("POST","/api/admin/tournaments",{"seasonId":999,"name":"Inexistente"}).status_code,404)

    def test_roster_duplicates_global_catalog_and_safe_removal(self):
        id=self.tournament()
        self.enroll(id)
        self.assertEqual(self.api("POST",f"/api/admin/tournaments/{id}/teams",{"teamId":1}).status_code,409)
        self.assertEqual(self.api("POST",f"/api/admin/tournaments/{id}/teams",{"teamId":999}).status_code,404)
        self.assertEqual(len(self.api("GET",f"/api/tournaments/{id}/teams").json),2)
        self.assertEqual(len(self.api("GET","/api/admin/teams").json),3)
        self.assertEqual(self.api("DELETE",f"/api/admin/tournaments/{id}/teams/2").status_code,200)
        self.assertEqual(self.api("DELETE",f"/api/admin/tournaments/1/teams/1").status_code,409)

    def test_jornada_numbers_and_cross_tournament_modification(self):
        id=self.tournament()
        jornada=self.jornada(id)
        self.assertEqual(self.api("POST","/api/admin/jornadas",{"number":1},id).status_code,409)
        self.assertEqual(self.api("PUT",f"/api/admin/jornadas/{jornada}",{"number":3},1).status_code,404)
        self.assertEqual(self.api("DELETE",f"/api/admin/jornadas/{jornada}",tournament=1).status_code,404)
        self.assertEqual(self.api("POST","/api/admin/jornadas",{"number":2,"tournamentId":1},id).status_code,400)
        self.assertEqual(backend.app.test_cli_runner().invoke(args=["init-scheduling"]).exit_code,0)
        self.assertEqual(backend.app.test_cli_runner().invoke(args=["init-business-rules"]).exit_code,0)
        self.assertEqual(self.jornada(id,2)>0,True)

    def test_only_registered_teams_and_tournament_dates(self):
        id=self.tournament(startDate="2026-07-01",endDate="2026-07-31")
        jornada=self.jornada(id)
        self.assertEqual(self.match(id,jornada).status_code,400)
        self.enroll(id)
        self.assertEqual(self.match(id,jornada,date="2026-06-30").status_code,400)
        match=self.match(id,jornada)
        self.assertEqual(match.status_code,201,match.text)
        match_id=match.json["matchId"]
        data={"team1Id":1,"team2Id":2,"date":"2026-07-15","time":"21:00"}
        self.assertEqual(self.api("PUT",f"/api/admin/matches/{match_id}",data,1).status_code,404)
        self.assertEqual(self.api("PUT",f"/api/admin/matches/{match_id}/result",{"sets":[{"team1Points":25,"team2Points":0}]*3},1).status_code,404)
        self.assertEqual(self.api("DELETE",f"/api/admin/tournaments/{id}/teams/1").status_code,409)
        self.assertEqual(self.api("PUT",f"/api/admin/tournaments/{id}",{"endDate":"2026-07-10"}).status_code,409)

    def test_schedules_and_standings_independent_between_tournaments(self):
        ids=[self.tournament("Torneo A"),self.tournament("Torneo B")]
        matches=[]
        for id in ids:
            self.enroll(id)
            jornada=self.jornada(id)
            r=self.match(id,jornada)
            self.assertEqual(r.status_code,201,r.text)
            matches.append(r.json["matchId"])
        for tournament,match_id,points in zip(ids,matches,[(25,0),(0,25)]):
            sets=[{"team1Points":points[0],"team2Points":points[1]}]*3
            self.assertEqual(self.api("PUT",f"/api/admin/matches/{match_id}/result",{"sets":sets},tournament).status_code,200)
        before=self.api("GET",f"/api/tournaments/{ids[1]}/standings").json
        self.assertEqual(before[0]["team"],"Dos")
        self.assertEqual(self.api("GET",f"/api/tournaments/{ids[0]}/standings").json[0]["team"],"Uno")
        self.assertEqual(len(before),2)
        self.api("PUT",f"/api/admin/matches/{matches[0]}/result",{"sets":[{"team1Points":0,"team2Points":25}]*3},ids[0])
        self.assertEqual(self.api("GET",f"/api/tournaments/{ids[1]}/standings").json,before)

    def test_activation_and_legacy_public_shapes(self):
        original=self.api("GET","/api/jornadas").json
        id=self.tournament()
        self.enroll(id,(3,))
        self.assertEqual(self.api("POST",f"/api/admin/tournaments/{id}/activate").status_code,200)
        self.assertEqual(self.api("GET","/api/tournaments/active").json["id"],id)
        self.assertEqual([t["id"] for t in self.api("GET","/api/teams").json],[3])
        self.assertEqual(self.api("GET","/api/jornadas").json,[])
        self.assertEqual(self.api("GET","/api/standings").json,[{"team":"Tres","teamId":3,"logo":"","wins":0,"losses":0,"setsWon":0,"setsLost":0}])
        self.assertEqual(self.api("GET","/api/tournaments/1/jornadas").json,original)
        self.assertEqual(self.api("GET","/api/jornadas?tournament_id=1").json,original)
        self.assertEqual(self.api("GET","/api/teams?tournament_id=abc").status_code,400)
        self.assertEqual(self.api("GET","/api/standings?tournament_id=999").status_code,404)

    def test_closed_tournament_history_immutable_and_archive(self):
        id=self.tournament()
        self.enroll(id)
        jornada=self.jornada(id)
        match=self.match(id,jornada).json["matchId"]
        self.assertEqual(self.api("PUT",f"/api/admin/tournaments/{id}",{"status":"completed"}).status_code,409)
        scores={"sets":[{"team1Points":25,"team2Points":0}]*3}
        self.assertEqual(self.api("PUT",f"/api/admin/matches/{match}/result",scores,id).status_code,200)
        self.assertEqual(self.api("POST",f"/api/admin/tournaments/{id}/activate").status_code,200)
        self.assertEqual(self.api("PUT",f"/api/admin/tournaments/{id}",{"status":"completed"}).status_code,200)
        historical=self.api("GET",f"/api/tournaments/{id}/standings").json
        for method,path,data in [("POST","/api/admin/jornadas",{"number":2}),("PUT",f"/api/admin/matches/{match}/result",scores),("DELETE",f"/api/admin/matches/{match}",None),("PUT",f"/api/admin/jornadas/{jornada}",{"number":2})]:
            self.assertEqual(self.api(method,path,data,id).status_code,409)
        self.assertEqual(self.api("POST",f"/api/admin/tournaments/{id}/teams",{"teamId":3}).status_code,409)
        self.assertEqual(self.api("POST",f"/api/admin/tournaments/{id}/activate").status_code,409)
        self.assertEqual(self.api("PUT",f"/api/admin/tournaments/{id}",{"name":"Cambio"}).status_code,409)
        self.assertEqual(self.api("PUT",f"/api/admin/tournaments/{id}",{"status":"archived"}).status_code,200)
        self.assertEqual(self.api("PUT",f"/api/admin/tournaments/{id}",{"status":"active"}).status_code,409)
        self.assertEqual(self.api("GET",f"/api/tournaments/{id}/standings").json,historical)
        self.assertEqual(self.api("GET","/api/jornadas").json,[])

    def test_season_closure_requires_closed_children(self):
        self.assertEqual(self.api("PUT","/api/admin/seasons/1",{"status":"completed"}).status_code,409)
        self.assertEqual(self.api("PUT","/api/admin/tournaments/1",{"status":"archived"}).status_code,200)
        self.assertEqual(self.api("PUT","/api/admin/seasons/1",{"status":"completed"}).status_code,200)
        self.assertEqual(self.api("POST","/api/admin/tournaments",{"seasonId":1,"name":"No permitido"}).status_code,409)
        self.assertEqual(self.api("PUT","/api/admin/seasons/1",{"name":"Cambio"}).status_code,409)
        self.assertEqual(self.api("PUT","/api/admin/seasons/1",{"status":"archived"}).status_code,200)

    def test_database_guards_preserve_associations_and_closed_results(self):
        id=self.tournament()
        jornada=self.jornada(id)
        for sql,args in [("UPDATE jornadas SET tournament_id=%s WHERE id=1",(id,)),("UPDATE matches SET jornada_id=%s WHERE id=1",(jornada,)),("DELETE FROM tournament_teams WHERE tournament_id=1 AND team_id=1",())]:
            with self.assertRaises(psycopg.IntegrityError):
                with self.connect() as conn: conn.execute(sql,args)
        self.api("PUT","/api/admin/tournaments/1",{"status":"archived"})
        for sql in ("UPDATE match_sets SET team1_points=26 WHERE match_id=1","DELETE FROM match_sets WHERE match_id=1","UPDATE match_sets SET match_id=2 WHERE match_id=1","UPDATE tournaments SET status='active' WHERE id=1"):
            with self.assertRaises(psycopg.IntegrityError):
                with self.connect() as conn: conn.execute(sql)

    def test_migration_rerun_preserves_data_and_public_selection(self):
        id=self.tournament()
        self.api("POST",f"/api/admin/tournaments/{id}/activate")
        self.api("DELETE","/api/admin/matches/2",tournament=1)
        self.api("DELETE","/api/admin/tournaments/1/teams/3")
        with self.connect() as conn:
            before=[conn.execute(q).fetchall() for q in ("SELECT * FROM teams ORDER BY id","SELECT * FROM matches ORDER BY id","SELECT * FROM match_sets ORDER BY match_id,set_number","SELECT * FROM tournament_teams ORDER BY tournament_id,team_id")]
        result=backend.app.test_cli_runner().invoke(args=["init-competitions"])
        self.assertEqual(result.exit_code,0,result.output)
        with self.connect() as conn:
            after=[conn.execute(q).fetchall() for q in ("SELECT * FROM teams ORDER BY id","SELECT * FROM matches ORDER BY id","SELECT * FROM match_sets ORDER BY match_id,set_number","SELECT * FROM tournament_teams ORDER BY tournament_id,team_id")]
        self.assertEqual(after,before)
        self.assertEqual(self.api("GET","/api/tournaments/active").json["id"],id)

    def test_authentication_and_csrf_new_management_routes(self):
        guest=backend.app.test_client()
        for path in ("/api/admin/seasons","/api/admin/tournaments","/api/admin/seasons/1/tournaments","/api/admin/tournaments/1/teams"):
            self.assertEqual(guest.get(path).status_code,401)
        for method,path in [("POST","/api/admin/seasons"),("PUT","/api/admin/seasons/1"),("POST","/api/admin/tournaments"),("PUT","/api/admin/tournaments/1"),("POST","/api/admin/tournaments/1/activate"),("POST","/api/admin/tournaments/1/teams"),("DELETE","/api/admin/tournaments/1/teams/1")]:
            self.assertEqual(guest.open(path,method=method,json={}).status_code,401)
            self.assertEqual(self.client.open(path,method=method,json={}).status_code,403)
        self.assertEqual(self.api("DELETE","/api/admin/seasons/1").status_code,405)
        self.assertEqual(self.api("DELETE","/api/admin/tournaments/1").status_code,405)
        for path in ("/api/tournaments","/api/tournaments/active","/api/tournaments/1/teams","/api/tournaments/1/jornadas","/api/tournaments/1/standings"):
            self.assertEqual(guest.get(path).status_code,200)

    def test_concurrent_public_activation_is_unique(self):
        ids=[self.tournament("A"),self.tournament("B")]
        cookie=self.client.get_cookie("voli_session").value
        barrier=Barrier(2)
        def activate(id):
            client=backend.app.test_client();client.set_cookie("voli_session",cookie)
            barrier.wait(timeout=10)
            return client.post(f"/api/admin/tournaments/{id}/activate",headers=self.headers).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(activate,ids))
        self.assertEqual(results,[200,200])
        with self.connect() as conn:
            rows=conn.execute("SELECT id FROM tournaments WHERE is_public=TRUE").fetchall()
        self.assertEqual(len(rows),1)
        self.assertIn(rows[0][0],ids)
