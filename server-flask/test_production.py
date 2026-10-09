import os
import secrets
import unittest
from unittest.mock import patch

os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_hex(32))
import app as backend
from configuration import settings
import psycopg
from reliability import checked_rows, DATA_LIMIT
from werkzeug.exceptions import ServiceUnavailable
import test_auth as auth_tests


class ProductionTests(unittest.TestCase):
    def config(self, **changes):
        return {"FLASK_SECRET_KEY":secrets.token_hex(32),"APP_ENV":"production","DATABASE_URL":"dbname=test","TRUSTED_HOSTS":"liga.example",**changes}

    def test_production_requires_explicit_configuration(self):
        for change in ({"FLASK_SECRET_KEY":"short"},{"DATABASE_URL":""},{"TRUSTED_HOSTS":""},{"TRUSTED_HOSTS":"https://liga.example"},{"TRUSTED_HOSTS":"*"},{"TRUSTED_HOSTS":"."},{"TRUSTED_HOSTS":"evil@host"},{"APP_ENV":"other"},{"FLASK_DEBUG":"1"},{"TRUST_PROXY":"yes"}):
            with self.assertRaises(RuntimeError): settings(self.config(**change))
        config=settings(self.config())
        self.assertTrue(config["SESSION_COOKIE_SECURE"])
        self.assertEqual(config["TRUSTED_HOSTS"],["liga.example"])
        self.assertEqual(config["SESSION_COOKIE_NAME"],"__Host-voli_session")

    def test_https_and_trusted_host_enforced_without_database(self):
        with patch.dict(backend.app.config,PRODUCTION=True,TRUSTED_HOSTS=["liga.example"]), patch.object(backend,"get_db_connection") as db:
            client=backend.app.test_client()
            for url in ("http://liga.example","https://attacker.example"):
                response=client.get("/api/admin/stats",base_url=url)
                self.assertEqual(response.status_code,400)
                self.assertNotIn("Bad Request",response.text)
            db.assert_not_called()
            response=client.get("/",base_url="https://liga.example")
            self.assertEqual(response.status_code,200)
            response.close()

    def test_public_security_headers(self):
        response=backend.app.test_client().get("/")
        self.assertEqual(response.headers["X-Frame-Options"],"DENY")
        self.assertIn("object-src 'none'",response.headers["Content-Security-Policy"])
        self.assertIn("script-src 'self'",response.headers["Content-Security-Policy"])
        self.assertNotIn("kit.fontawesome.com",response.text)
        self.assertEqual(response.headers["X-Content-Type-Options"],"nosniff")
        self.assertIn("camera=()",response.headers["Permissions-Policy"])
        response.close()

    def test_database_errors_are_unavailable_and_logs_redacted(self):
        sensitive="password=secret SQL team name private"
        with patch.object(backend,"get_db_connection",side_effect=psycopg.OperationalError(sensitive)), self.assertLogs(backend.app.logger,level="ERROR") as logs:
            response=backend.app.test_client().get("/api/jornadas")
        self.assertEqual(response.status_code,503)
        self.assertNotIn(sensitive,response.text)
        self.assertNotIn(sensitive,"".join(logs.output))

    def test_connections_have_bounded_waits(self):
        with patch("app.psycopg.connect") as connect:
            backend.get_db_connection()
        self.assertEqual(connect.call_args.kwargs["connect_timeout"],5)
        self.assertIn("statement_timeout=15000",connect.call_args.kwargs["options"])
        self.assertIn("lock_timeout=5000",connect.call_args.kwargs["options"])

    def test_oversized_and_excessive_forms_rejected(self):
        client=backend.app.test_client()
        response=client.post("/login",data={"password":"x"*70000})
        self.assertEqual(response.status_code,413)
        self.assertIn("demasiado grande",response.json["error"])
        response=client.post("/login",data={str(i):"x" for i in range(21)},content_type="multipart/form-data")
        self.assertEqual(response.status_code,413)

    def test_bounded_legacy_queries_fail_without_partial_data(self):
        with self.assertRaises(ServiceUnavailable): checked_rows([None]*(DATA_LIMIT+1))
        self.assertEqual(checked_rows([]),[])

    def test_public_catalog_pagination_validation(self):
        client=backend.app.test_client()
        for query in ("limit=0","limit=501","offset=-1","limit=abc","offset=1000001"):
            self.assertEqual(client.get("/api/tournaments?"+query).status_code,400)


class MalformedApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth_tests.AuthenticationTests.setUpClass()

    def setUp(self):
        self.auth=auth_tests.AuthenticationTests()
        self.auth.setUp()
        self.addCleanup(self.auth.tearDown)
        self.auth.login()
        self.client=self.auth.client
        self.headers={"X-CSRF-Token":self.auth.session_token()}

    def test_malformed_json_state_changes_fail_without_writes(self):
        paths=["/api/admin/seasons","/api/admin/tournaments","/api/admin/teams","/api/admin/jornadas","/api/admin/tournaments/1/teams"]
        for path in paths:
            for body in ("{", "[]", "null", '"text"'):
                response=self.client.post(path,data=body,content_type="application/json",headers=self.headers)
                self.assertEqual(response.status_code,400,(path,body,response.text))
        for body in ("{","[]","null"):
            response=self.client.put("/api/admin/matches/1/result",data=body,content_type="application/json",headers=self.headers)
            self.assertEqual(response.status_code,400)

    def test_unavailable_result_database_returns_503(self):
        token=self.headers
        with patch.object(backend,"get_db_connection",side_effect=psycopg.OperationalError("private connection")),self.assertLogs(backend.app.logger,level="ERROR"):
            response=self.client.put("/api/admin/matches/1/result",json={"sets":[{"team1Points":25,"team2Points":0}]*3},headers=token)
        self.assertEqual(response.status_code,503)
        self.assertNotIn("private connection",response.text)
