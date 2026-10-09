from datetime import timedelta
import os
import re
import secrets
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_hex(32))
import app as backend
import auth
from werkzeug.security import generate_password_hash

backend.app.add_url_rule('/api/future-write', 'future_write',
                         lambda: {'ok': True}, methods=['POST'])


class MemoryStore:
    def __init__(self):
        self.rows = {}

    def load(self, token):
        row = self.rows.get(token)
        return row if row and row[1] > auth.now() else None

    def save(self, token, data, expiry, new):
        if not new and token not in self.rows:
            return False
        self.rows[token] = (dict(data), expiry)
        return True

    def delete(self, token):
        self.rows.pop(token, None)


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(20)
        cls.password_hash = generate_password_hash(cls.password)

    def setUp(self):
        self.client = backend.app.test_client()
        self.store = MemoryStore()
        self.store_patch = patch.object(backend.app.session_interface, 'store', self.store)
        self.store_patch.start()
        # The route closures share the original store object; mock its methods too.
        original = backend.app.extensions['auth_session_store']
        self.patches = [patch.object(original, method, getattr(self.store, method))
                        for method in ('delete', 'load', 'save')]
        for item in self.patches:
            item.start()
        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection
        self.connection.execute.side_effect = self.execute
        cursor = self.connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []
        cursor.fetchone.return_value = (1, 1, 2, 1)
        self.counts = {}
        self.active = True
        self.db_patch = patch.object(backend, 'get_db_connection', return_value=self.connection)
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        for item in self.patches:
            item.stop()
        self.store_patch.stop()

    def execute(self, query, args=None):
        if query.startswith('SELECT id FROM tournaments'):
            return SimpleNamespace(fetchone=lambda: (1,))
        if query.startswith('SELECT t.id, t.status'):
            return SimpleNamespace(fetchone=lambda: (1,'active',None,None,'active'))
        if 'INSERT INTO administrator_login_attempts' in query:
            key = args[0]
            self.counts[key] = self.counts.get(key, 0) + 1
            return SimpleNamespace(fetchone=lambda: (self.counts[key],))
        if 'SELECT id, password_hash, active' in query:
            row = (1, self.password_hash, self.active) if args[0] == 'administrador' else None
            return SimpleNamespace(fetchone=lambda: row)
        if 'SELECT id, username' in query:
            row = (1, 'administrador', self.password_hash) if self.active else None
            return SimpleNamespace(fetchone=lambda: row)
        return MagicMock()

    def login_token(self):
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        return re.search(r'name="csrf_token" value="([^"]+)"', response.text)[1]

    def login(self, password=None):
        token = self.login_token()
        return self.client.post('/login', data={
            'username': 'administrador', 'password': password or self.password,
            'csrf_token': token,
        })

    def session_token(self):
        return self.client.get('/api/auth/session').json['csrf_token']

    def test_login_page_preserves_accessible_form_and_spanish_notices(self):
        page = self.client.get('/login?motivo=sesion')
        self.assertEqual(page.status_code, 200)
        for text in ('class="login-screen"', 'class="login-header"',
                     'action="/login" method="post" novalidate',
                     'autocomplete="username"', 'autocomplete="current-password"',
                     'label for="username"', 'label for="password"',
                     'Inicia sesión para acceder a la administración.',
                     'Volver a la liga'):
            self.assertIn(text, page.text)
        self.assertRegex(page.text, r'name="csrf_token" value="[^"]+"')
        self.assertIn('no-store', page.headers['Cache-Control'])
        self.assertIn('Has cerrado la sesión correctamente.',
                      self.client.get('/login?salida=1').text)

    def test_successful_login_rotates_session_and_csrf(self):
        token = self.login_token()
        old_cookie = self.client.get_cookie('voli_session').value
        response = self.client.post('/login', data={
            'username': 'administrador', 'password': self.password, 'csrf_token': token,
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.location, '/admin.html')
        self.assertNotEqual(old_cookie, self.client.get_cookie('voli_session').value)
        self.assertNotEqual(token, self.session_token())
        self.assertIn('HttpOnly', response.headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', response.headers['Set-Cookie'])
        self.assertNotIn(self.password, response.headers['Set-Cookie'])
        dashboard = self.client.get('/admin.html')
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn('no-store', dashboard.headers['Cache-Control'])
        self.assertNotIn('{{ csrf_token }}', dashboard.text)
        self.assertIn('class="admin-screen"', dashboard.text)
        self.assertIn('id="admin-nav"', dashboard.text)

    def test_incorrect_credentials(self):
        response = self.login(password='incorrecta')
        self.assertEqual(response.status_code, 401)
        self.assertIn('Usuario o contraseña incorrectos.', response.text)
        self.assertEqual(self.client.get('/api/admin/stats').status_code, 401)

    def test_logout_revokes_session_and_replay(self):
        self.login()
        old_cookie = self.client.get_cookie('voli_session').value
        response = self.client.post('/logout', data={'csrf_token': self.session_token()})
        self.assertEqual(response.status_code, 303)
        self.assertIsNone(self.client.get_cookie('voli_session'))
        self.client.set_cookie('voli_session', old_cookie)
        self.assertEqual(self.client.get('/api/admin/stats').status_code, 401)

    def test_session_expiration_is_enforced_server_side(self):
        self.login()
        for token, (data, expiry) in list(self.store.rows.items()):
            self.store.rows[token] = (data, auth.now() - timedelta(seconds=1))
        self.assertEqual(self.client.put('/api/admin/matches/1/result', json={}).status_code, 401)
        self.assertEqual(self.client.get('/admin.html').status_code, 303)

    def test_login_csrf_rejection(self):
        response = self.client.post('/login', data={'username': 'administrador', 'password': self.password})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('admin_id', next(iter(self.store.rows.values()))[0])

    def test_authenticated_csrf_rejection_and_correct_result(self):
        self.login()
        payload = {'sets': [{'team1Points': 25, 'team2Points': 0}] * 3}
        for token in ('', 'incorrecto', 'á'):
            response = self.client.put('/api/admin/matches/1/result', json=payload,
                                       headers={'X-CSRF-Token': token})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post('/logout').status_code, 403)
        self.assertEqual(self.client.put('/api/admin/matches/1/result', json=payload,
                         headers={'X-CSRF-Token': self.session_token()}).status_code, 200)

    def test_foreign_origin_is_rejected(self):
        self.login()
        response = self.client.post('/logout', data={'csrf_token': self.session_token()},
                                    headers={'Origin': 'https://otro.example'})
        self.assertEqual(response.status_code, 403)

    def test_protected_and_future_endpoints(self):
        for path, method in [('/api/admin/stats', 'get'), ('/api/auth/session', 'get'),
                             ('/api/admin/matches/1/result', 'put'), ('/api/future-write', 'post')]:
            self.assertEqual(getattr(self.client, method)(path).status_code, 401)
        self.assertEqual(self.client.get('/admin.js').status_code, 303)
        self.assertEqual(self.client.get('/scheduling.js').status_code, 303)
        self.assertEqual(self.client.get('/competitions.js').status_code, 303)
        self.login()
        script = self.client.get('/scheduling.js')
        self.assertEqual(script.status_code, 200)
        self.assertIn('no-store', script.headers['Cache-Control'])
        script.close()
        self.assertEqual(self.client.post('/api/future-write').status_code, 403)
        self.assertEqual(self.client.post('/api/future-write',
                         headers={'X-CSRF-Token': self.session_token()}).status_code, 200)

    def test_public_endpoints_are_accessible(self):
        for path in ('/', '/api/teams', '/api/jornadas', '/api/standings'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            response.close()
        self.assertEqual(self.store.rows, {})

    def test_disabled_administrator_loses_access(self):
        self.login()
        self.active = False
        self.assertEqual(self.client.get('/api/admin/stats').status_code, 401)

    def test_password_change_invalidates_sessions_created_during_reset_race(self):
        self.login()
        with patch.object(self, 'password_hash', generate_password_hash(secrets.token_urlsafe(20))):
            self.assertEqual(self.client.get('/api/admin/stats').status_code, 401)

    def test_malformed_credentials_are_rate_limited(self):
        token=self.login_token()
        for _ in range(10):
            self.assertEqual(self.client.post('/login',data={'username':'!','password':'x','csrf_token':token}).status_code,401)
        self.assertEqual(self.client.post('/login',data={'username':'!','password':'x','csrf_token':token}).status_code,429)

    def test_concurrent_revocation_cannot_report_successful_session_save(self):
        self.login()
        with patch.object(self.store,'save',return_value=False):
            with self.client.session_transaction() as data:
                data['extra']='changed'
        self.assertIsNone(self.client.get_cookie('voli_session'))

    def test_login_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.login(password='incorrecta').status_code, 401)
        response = self.login(password='incorrecta')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Retry-After'], '900')

    def test_production_cookie(self):
        with patch.dict(backend.app.config, SESSION_COOKIE_SECURE=True,
                        SESSION_COOKIE_NAME='__Host-voli_session'):
            response = backend.app.test_client().get('/login', base_url='https://liga.example')
            self.assertIn('__Host-voli_session=', response.headers['Set-Cookie'])
            self.assertIn('Secure;', response.headers['Set-Cookie'])
            self.assertIn('HttpOnly;', response.headers['Set-Cookie'])
            self.assertIn('SameSite=Lax', response.headers['Set-Cookie'])
            self.assertNotIn('Domain=', response.headers['Set-Cookie'])

    def test_store_failure_cannot_report_successful_login(self):
        self.login_token()
        with patch.object(self.store, 'save', side_effect=RuntimeError('storage unavailable')), \
                self.assertLogs(backend.app.logger, level='ERROR'):
            response = self.login()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('Location', response.headers)

    def test_password_hash_never_exposed(self):
        self.login()
        response = self.client.get('/api/auth/session')
        self.assertEqual(set(response.json), {'username', 'csrf_token'})
        self.assertNotIn(self.password_hash, response.text)

    def test_tampered_cookie_is_rejected(self):
        self.login()
        self.client.set_cookie('voli_session', 'alterada')
        self.assertEqual(self.client.get('/api/admin/stats').status_code, 401)

    def test_unknown_user_returns_same_error(self):
        token = self.login_token()
        response = self.client.post('/login', data={
            'username': 'inexistente', 'password': self.password, 'csrf_token': token,
        })
        self.assertEqual(response.status_code, 401)
        self.assertIn('Usuario o contraseña incorrectos.', response.text)

    def test_create_admin_cli_hashes_password(self):
        result = backend.app.test_cli_runner().invoke(args=[
            'create-admin', '--username', 'nuevo_admin',
        ], input=f'{self.password}\n{self.password}\n')
        self.assertEqual(result.exit_code, 0)
        query, params = self.connection.execute.call_args.args
        self.assertIn('INSERT INTO administrators', query)
        self.assertEqual(params[0], 'nuevo_admin')
        self.assertNotEqual(params[1], self.password)
        self.assertTrue(auth.check_password_hash(params[1], self.password))
        self.assertNotIn(self.password, result.output)

    def test_reset_password_revokes_sessions(self):
        result = backend.app.test_cli_runner().invoke(args=[
            'reset-admin-password', '--username', 'administrador',
        ], input=f'{self.password}\n{self.password}\n')
        self.assertEqual(result.exit_code, 0)
        queries = [call.args[0] for call in self.connection.execute.call_args_list]
        self.assertTrue(any('DELETE FROM administrator_sessions WHERE administrator_id' in q for q in queries))

    def test_login_storage_unavailable_fails_closed(self):
        self.login()
        with patch.object(self.store, 'load', side_effect=RuntimeError('storage unavailable')), \
                self.assertLogs(backend.app.logger, level='ERROR'):
            response = self.client.get('/admin.html')
        self.assertEqual(response.status_code, 503)

    def test_init_auth_only_adds_authentication_tables(self):
        result = backend.app.test_cli_runner().invoke(args=['init-auth'])
        self.assertEqual(result.exit_code, 0)
        query = self.connection.execute.call_args.args[0]
        self.assertIn('CREATE TABLE IF NOT EXISTS administrators', query)
        self.assertNotIn('DROP', query.upper())
        self.assertNotIn('DELETE', query.upper().replace('ON DELETE CASCADE', ''))


class StorageTests(unittest.TestCase):
    def test_store_hashes_identifiers_and_never_upserts_revoked_sessions(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.execute.return_value.rowcount = 0
        store = auth.SessionStore(lambda: conn)
        token = secrets.token_urlsafe(32)
        self.assertFalse(store.save(token, {'admin_id': 1}, auth.now(), False))
        query, args = conn.execute.call_args.args
        self.assertIn('UPDATE administrator_sessions', query)
        self.assertNotIn(token, args)
        self.assertIn(auth.token_hash(token), args)


if __name__ == '__main__':
    unittest.main()
