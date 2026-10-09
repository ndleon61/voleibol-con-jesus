import os
import re
import secrets
import unittest
from unittest.mock import patch

os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_hex(32))
import app as backend
import psycopg
from psycopg import sql
from werkzeug.security import generate_password_hash


@unittest.skipUnless(os.environ.get('AUTH_TEST_DATABASE_URL'), 'PostgreSQL de pruebas no configurado')
class PostgresAuthenticationTests(unittest.TestCase):
    def test_persistent_sessions_rotation_expiration_and_logout(self):
        database = os.environ['AUTH_TEST_DATABASE_URL']
        schema = 'auth_test_' + secrets.token_hex(8)
        with psycopg.connect(database) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))

        def connect():
            return psycopg.connect(database, options=f'-c search_path={schema}')

        try:
            with patch.object(backend, 'get_db_connection', side_effect=connect):
                migration = backend.app.test_cli_runner().invoke(args=['init-auth'])
                self.assertEqual(migration.exit_code, 0, migration.output)
                password = secrets.token_urlsafe(20)
                with connect() as conn:
                    conn.execute('INSERT INTO administrators (username, password_hash) VALUES (%s, %s)',
                                 ('prueba', generate_password_hash(password)))
                client = backend.app.test_client()

                def login():
                    page = client.get('/login')
                    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
                    response = client.post('/login', data={
                        'username': 'prueba', 'password': password, 'csrf_token': token,
                    })
                    self.assertEqual(response.status_code, 303)
                    return client.get('/api/auth/session').json['csrf_token']

                csrf = login()
                cookie = client.get_cookie('voli_session').value
                self.assertEqual(client.get('/admin.html').status_code, 200)
                with connect() as conn:
                    rows = conn.execute('SELECT token_hash, data FROM administrator_sessions').fetchall()
                    self.assertEqual(len(rows), 1)
                    self.assertNotEqual(rows[0][0], cookie)
                    self.assertNotIn('password_hash', rows[0][1])
                self.assertEqual(client.post('/logout', data={'csrf_token': csrf}).status_code, 303)
                client.set_cookie('voli_session', cookie)
                self.assertEqual(client.get('/api/auth/session').status_code, 401)
                login()
                with connect() as conn:
                    conn.execute("UPDATE administrator_sessions SET expires_at = CURRENT_TIMESTAMP - INTERVAL '1 second'")
                self.assertEqual(client.get('/api/auth/session').status_code, 401)
                self.assertEqual(client.get('/admin.html').status_code, 303)
        finally:
            # Only the unique schema created by this test is removed.
            with psycopg.connect(database) as conn:
                conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    unittest.main()
