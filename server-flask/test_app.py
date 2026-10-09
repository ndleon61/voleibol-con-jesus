import unittest
import os
import secrets
from unittest.mock import MagicMock, patch
os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_hex(32))
import app as backend


class AppTests(unittest.TestCase):
    def test_score_validation(self):
        for winner, loser, valid in [(25, 0, True), (26, 24, True),
                                     (27, 25, True), (26, 0, False),
                                     (27, 24, False), (25, -1, False),
                                     (25.5, 0, False)]:
            with self.subTest(winner=winner, loser=loser):
                result = backend.validate_sets([
                    {"team1Points": winner, "team2Points": loser}
                ] * 3)
                self.assertEqual(isinstance(result, list), valid)

    def test_fifth_set_and_match_end(self):
        sets = [{"team1Points": 25, "team2Points": 0},
                {"team1Points": 0, "team2Points": 25}] * 2
        self.assertIsInstance(backend.validate_sets(
            sets + [{"team1Points": 15, "team2Points": 0}]), list)
        self.assertIsInstance(backend.validate_sets(
            sets + [{"team1Points": 16, "team2Points": 0}]), str)
        self.assertIsInstance(backend.validate_sets(
            [{"team1Points": 25, "team2Points": 0}] * 4), str)

    def test_static_routes_do_not_expose_backend(self):
        client = backend.app.test_client()
        for path in ['/', '/app.js', '/media/los_lobos.JPG']:
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            response.close()
        self.assertEqual(client.get('/app.py').status_code, 404)
        self.assertEqual(client.get('/admin.html').status_code, 303)

    def test_standings_skip_incomplete_and_out_of_order_results(self):
        connection = MagicMock()
        cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [(1, 'A', None), (2, 'B', None)],
            [(1, 1, 2, 1, 25, 0)] +
            [(2, 1, 2, n, 25, 0) for n in (1, 2, 3)] +
            [(3, 1, 2, n, 25, 0) for n in (1, 3, 4)],
        ]
        with patch.object(backend, 'get_db_connection', return_value=connection):
            response = backend.app.test_client().get('/api/standings')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json[0]['wins'], 1)
        self.assertEqual(response.json[0]['setsWon'], 3)


if __name__ == '__main__':
    unittest.main()
