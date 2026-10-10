import unittest
import os
import secrets
from unittest.mock import MagicMock, patch
os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_hex(32))
import app as backend


class AppTests(unittest.TestCase):
    def test_best_of_three_scores_and_deciding_set(self):
        def sets(*scores):
            return [{"team1Points": a, "team2Points": b} for a, b in scores]
        for scores in (sets((25, 10), (25, 23)), sets((0, 25), (0, 25)),
                       sets((25, 23), (22, 25), (25, 20)), sets((25, 0), (0, 25), (24, 26))):
            self.assertIsInstance(backend.validate_sets(scores, 3), list)
        for scores in (sets((25, 0)), sets((25, 0), (0, 25)),
                       sets((25, 0), (25, 0), (15, 0)),
                       sets((25, 0), (0, 25), (14, 12)),
                       sets((25, 0), (0, 25), (26, 20)),
                       sets((25, 0), (0, 25), (15, 13)),
                       sets((25, 0), (0, 25), (25, 24))):
            self.assertIsInstance(backend.validate_sets(scores, 3), str)
        for format in (True, "3", 4, None):
            self.assertIsInstance(backend.validate_sets(sets((25, 0), (25, 0)), format), str)
        self.assertIsInstance(backend.validate_sets(sets((25, 0), (25, 0))), list)

    def test_shared_best_of_three_scores(self):
        import json
        from pathlib import Path
        fixtures = json.loads((Path(__file__).parent.parent / "tests/match-formats.json").read_text())
        for item in fixtures:
            with self.subTest(item["name"]):
                scores = [{"team1Points": a, "team2Points": b} for a, b in item["sets"]]
                self.assertEqual(isinstance(backend.validate_sets(scores, item["bestOf"]), list), item["valid"])

    def test_score_validation(self):
        for winner, loser, valid in [(25, 0, True), (26, 24, True),
                                     (27, 25, True), (26, 0, False),
                                     (27, 24, False), (25, -1, False),
                                     (25.5, 0, False)]:
            with self.subTest(winner=winner, loser=loser):
                result = backend.validate_sets([
                    {"team1Points": winner, "team2Points": loser}
                ] * 3, 5)
                self.assertEqual(isinstance(result, list), valid)

    def test_fifth_set_and_match_end(self):
        sets = [{"team1Points": 25, "team2Points": 0},
                {"team1Points": 0, "team2Points": 25}] * 2
        self.assertIsInstance(backend.validate_sets(
            sets + [{"team1Points": 15, "team2Points": 0}], 5), list)
        self.assertIsInstance(backend.validate_sets(
            sets + [{"team1Points": 16, "team2Points": 0}], 5), str)
        self.assertIsInstance(backend.validate_sets(
            [{"team1Points": 25, "team2Points": 0}] * 4, 5), str)

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
            [(1, 1, 2, 1, 25, 0, 5)] +
            [(2, 1, 2, n, 25, 0, 5) for n in (1, 2, 3)] +
            [(3, 1, 2, n, 25, 0, 5) for n in (1, 3, 4)],
        ]
        with patch.object(backend, 'get_db_connection', return_value=connection):
            response = backend.app.test_client().get('/api/standings')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json[0]['wins'], 1)
        self.assertEqual(response.json[0]['setsWon'], 3)

    def test_public_season_catalog_is_read_only_and_contains_no_admin_fields(self):
        connection = MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchall.return_value = [
            (1, 'Temporada original', None, None, 'active'),
        ]
        client = backend.app.test_client()
        with patch.object(backend, 'get_db_connection', return_value=connection):
            response = client.get('/api/seasons?limit=10&offset=0')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, [dict(id=1, name='Temporada original',
                                            startDate=None, endDate=None, status='active')])
        query, params = connection.__enter__.return_value.execute.call_args.args
        self.assertIn('LIMIT %s OFFSET %s', query)
        self.assertEqual(params, (10, 0))
        self.assertEqual(client.get('/api/admin/seasons').status_code, 401)
        self.assertEqual(client.post('/api/seasons', json={}).status_code, 401)
        self.assertEqual(client.get('/api/seasons?limit=9999').status_code, 400)


if __name__ == '__main__':
    unittest.main()
