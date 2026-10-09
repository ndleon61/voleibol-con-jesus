import os
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from backup import backup,restore
from PIL import Image
import test_competitions as competition_tests
import app as backend


@unittest.skipUnless(os.environ.get('AUTH_TEST_DATABASE_URL'),'PostgreSQL de pruebas no configurado')
class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        competition_tests.CompetitionTests.setUpClass()
        cls.addClassCleanup(competition_tests.CompetitionTests.doClassCleanups)

    def setUp(self):
        self.fixture=competition_tests.CompetitionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.client
        self.headers=self.fixture.headers
        self.connect=self.fixture.connect
        self.api=self.fixture.api
        self.directory=TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        change=patch.dict(backend.app.config,TEAM_LOGO_DIRECTORY=self.directory.name)
        change.start();self.addCleanup(change.stop)

    def logo(self,color='red'):
        output=BytesIO();Image.new('RGB',(20,20),color).save(output,format='PNG')
        return output.getvalue()

    def update(self,name='Actual',image=None,remove=False):
        data={'name':name,'remove_logo':'true' if remove else 'false'}
        if image: data['logo']=(BytesIO(image),'logo.png')
        return self.client.put('/api/admin/teams/1',data=data,headers=self.headers)

    def rows(self):
        with self.connect() as conn:
            return conn.execute('SELECT * FROM tournament_teams ORDER BY tournament_id,team_id').fetchall()

    def test_completion_names_logos_and_history_remain_stable(self):
        url=self.update('Nombre original',self.logo()).json['team']['logo']
        self.api('DELETE','/api/admin/matches/2',tournament=1)
        self.assertEqual(self.api('PUT','/api/admin/tournaments/1',{'status':'completed'}).status_code,200)
        before=self.api('GET','/api/tournaments/1/standings').json
        calendar=self.api('GET','/api/tournaments/1/jornadas').json
        snapshot=self.rows()
        self.assertEqual(self.update('Nombre nuevo',self.logo('blue')).status_code,200)
        self.assertEqual(self.update('Nombre nuevo',remove=True).status_code,200)
        self.assertEqual(self.api('GET','/api/tournaments/1/standings').json,before)
        self.assertEqual(self.api('GET','/api/tournaments/1/jornadas').json,calendar)
        self.assertEqual(calendar[0]['games'][0]['team1Id'],1)
        self.assertEqual(calendar[0]['games'][0]['team1Logo'],url)
        response=self.client.get(url);self.assertEqual(response.status_code,200);response.close()
        for status in ('completed','completed','archived','archived'):
            self.assertEqual(self.api('PUT','/api/admin/tournaments/1',{'status':status}).status_code,200)
            self.assertEqual(self.rows(),snapshot)

    def test_active_identity_and_distinct_tournament_snapshots(self):
        first=self.fixture.tournament('Primero');self.fixture.enroll(first)
        self.update('Identidad primera')
        self.assertEqual(self.api('GET',f'/api/tournaments/{first}/teams').json[0]['name'],'Identidad primera')
        self.api('PUT',f'/api/admin/tournaments/{first}',{'status':'archived'})
        second=self.fixture.tournament('Segundo');self.fixture.enroll(second)
        self.update('Identidad segunda')
        self.assertEqual(self.api('GET',f'/api/tournaments/{second}/teams').json[0]['name'],'Identidad segunda')
        self.api('PUT',f'/api/admin/tournaments/{second}',{'status':'completed'})
        self.assertEqual(self.api('GET',f'/api/tournaments/{first}/teams').json[0]['name'],'Identidad primera')
        self.assertEqual(self.api('GET',f'/api/tournaments/{second}/teams').json[0]['name'],'Identidad segunda')

    def test_missing_and_unsafe_logo_roll_back_closure(self):
        for url in ('/team-logos/'+'a'*32+'.webp','/media/../../auth.py','https://example.com/logo'):
            with self.connect() as conn: conn.execute('UPDATE teams SET logo_path=%s WHERE id=1',(url,))
            self.assertEqual(self.api('PUT','/api/admin/tournaments/1',{'status':'archived'}).status_code,409)
            self.assertTrue(all(row[2] is None for row in self.rows()))
            with self.connect() as conn:
                self.assertEqual(conn.execute('SELECT status FROM tournaments WHERE id=1').fetchone()[0],'active')

    def test_failure_after_capture_rolls_back_status_and_all_snapshots(self):
        with self.connect() as conn:
            conn.execute("CREATE FUNCTION reject_snapshot_close() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private_test_failure'; END $$")
            conn.execute('CREATE TRIGGER zz_reject_snapshot_close AFTER UPDATE OF status ON tournaments FOR EACH ROW EXECUTE FUNCTION reject_snapshot_close()')
        try:
            with self.assertLogs(backend.app.logger,level='ERROR'):
                response=self.api('PUT','/api/admin/tournaments/1',{'status':'archived'})
            self.assertEqual(response.status_code,503)
            self.assertNotIn('private_test_failure',response.text)
            self.assertTrue(all(row[2] is None and row[4] is None for row in self.rows()))
            with self.connect() as conn:
                self.assertEqual(conn.execute('SELECT status FROM tournaments WHERE id=1').fetchone()[0],'active')
        finally:
            with self.connect() as conn:
                conn.execute('DROP TRIGGER zz_reject_snapshot_close ON tournaments')
                conn.execute('DROP FUNCTION reject_snapshot_close()')

    def test_legacy_logos_materialized_once(self):
        with self.connect() as conn:
            conn.execute("UPDATE teams SET logo_path='/media/los_lobos.JPG' WHERE id=1")
        first=self.fixture.tournament('Uno');self.fixture.enroll(first)
        second=self.fixture.tournament('Dos');self.fixture.enroll(second)
        for id in (first,second):
            response=self.api('PUT',f'/api/admin/tournaments/{id}',{'status':'archived'})
            self.assertEqual(response.status_code,200,response.text)
        a=self.api('GET',f'/api/tournaments/{first}/teams').json[0]['logo']
        b=self.api('GET',f'/api/tournaments/{second}/teams').json[0]['logo']
        self.assertEqual(a,b);self.assertTrue(a.startswith('/team-logos/'))
        self.assertEqual(len(list(Path(self.directory.name).iterdir())),1)

    def test_sql_guards_authentication_and_migration_rerun(self):
        self.api('PUT','/api/admin/tournaments/1',{'status':'archived'})
        before=self.rows()
        for query in ("UPDATE tournament_teams SET team_name_snapshot='Cambio' WHERE tournament_id=1",'UPDATE tournament_teams SET snapshot_created_at=NULL WHERE tournament_id=1'):
            with self.assertRaises(psycopg.IntegrityError):
                with self.connect() as conn: conn.execute(query)
        guest=backend.app.test_client()
        self.assertEqual(guest.put('/api/admin/tournaments/1',json={'status':'archived'}).status_code,401)
        self.assertEqual(self.client.put('/api/admin/tournaments/1',json={'status':'archived'}).status_code,403)
        for command in ('init-snapshots','init-competitions','init-scheduling','init-business-rules','init-snapshots'):
            result=backend.app.test_cli_runner().invoke(args=[command])
            self.assertEqual(result.exit_code,0,result.output)
            self.assertEqual(self.rows(),before)

    def test_existing_closed_registration_backfill_preserves_partial_values(self):
        self.api('PUT','/api/admin/tournaments/1',{'status':'archived'})
        with self.connect() as conn:
            conn.execute('DROP TRIGGER roster_competition_guard ON tournament_teams')
            conn.execute("UPDATE tournament_teams SET team_name_snapshot=CASE WHEN team_id=1 THEN 'Valor conservado' ELSE NULL END,team_logo_snapshot=NULL,snapshot_created_at=NULL")
            before=conn.execute('SELECT * FROM match_sets ORDER BY match_id,set_number').fetchall()
        result=backend.app.test_cli_runner().invoke(args=['init-snapshots'])
        self.assertEqual(result.exit_code,0,result.output)
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT * FROM match_sets ORDER BY match_id,set_number').fetchall(),before)
        self.assertEqual(self.rows()[0][2],'Valor conservado')
        self.assertTrue(all(row[2] and row[4] for row in self.rows()))
        saved=self.rows()
        self.assertEqual(backend.app.test_cli_runner().invoke(args=['init-snapshots']).exit_code,0)
        self.assertEqual(self.rows(),saved)

    def test_backup_restoration_includes_snapshots_and_retained_logo(self):
        import secrets
        url=self.update('Histórico',self.logo()).json['team']['logo']
        self.api('PUT','/api/admin/tournaments/1',{'status':'archived'})
        self.update('Actual',remove=True)
        name='voli_restore_snapshot_'+secrets.token_hex(6)
        with self.connect() as conn: schema=conn.execute('SELECT current_schema()').fetchone()[0]
        database=make_conninfo(os.environ['AUTH_TEST_DATABASE_URL'],options=f'-c search_path={schema}')
        maintenance=make_conninfo(database,dbname='postgres')
        def cleanup():
            with psycopg.connect(maintenance,autocommit=True) as conn:
                conn.execute(sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(name)))
        self.addCleanup(cleanup)
        with TemporaryDirectory() as directory:
            source=Path(directory)/'backup';destination=Path(directory)/'logos'
            backup(database,self.directory.name,source)
            target=restore(source,database,name,destination)
            with psycopg.connect(target) as conn:
                restored=conn.execute('SELECT * FROM tournament_teams ORDER BY tournament_id,team_id').fetchall()
            self.assertEqual(restored,self.rows())
            filename=url.rsplit('/',1)[1]
            self.assertEqual((destination/filename).read_bytes(),(Path(self.directory.name)/filename).read_bytes())

    def test_concurrent_name_and_logo_update_is_consistent(self):
        old=self.update('Anterior',self.logo()).json['team']['logo']
        cookie=self.client.get_cookie('voli_session').value
        barrier=Barrier(2)
        def close():
            client=backend.app.test_client();client.set_cookie('voli_session',cookie);barrier.wait(timeout=10)
            return client.put('/api/admin/tournaments/1',json={'status':'archived'},headers=self.headers)
        def change():
            client=backend.app.test_client();client.set_cookie('voli_session',cookie);barrier.wait(timeout=10)
            return client.put('/api/admin/teams/1',data={'name':'Posterior','logo':(BytesIO(self.logo('blue')),'logo.png')},headers=self.headers)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(close);b=pool.submit(change);closed,updated=a.result(timeout=20),b.result(timeout=20)
        self.assertEqual(closed.status_code,200,closed.text)
        self.assertEqual(updated.status_code,200,updated.text)
        historical=self.api('GET','/api/tournaments/1/teams').json[0]
        self.assertIn((historical['name'],historical['logo']),{('Anterior',old),('Posterior',updated.json['team']['logo'])})
        response=self.client.get(historical['logo']);self.assertEqual(response.status_code,200);response.close()
