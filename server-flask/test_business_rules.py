import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import test_app
import app as backend

FIXTURES = json.loads((Path(__file__).parent.parent / "tests/business-rules.json").read_text())


class BusinessRulesTests(unittest.TestCase):
    def test_shared_scoring_fixtures(self):
        for fixture in FIXTURES["scores"]:
            with self.subTest(fixture["name"]):
                sets = [{"team1Points": p1, "team2Points": p2} for p1, p2 in fixture["sets"]]
                if "numbers" in fixture:
                    for item, number in zip(sets, fixture["numbers"]):
                        item["setNumber"] = number
                self.assertEqual(isinstance(backend.validate_sets(sets, 5), list), fixture["valid"])

    def test_standings_match_shared_frontend_fixture(self):
        connection = MagicMock()
        cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [(t["id"], t["name"], None) for t in FIXTURES["teams"]],
            [(m["id"], m["team1"], m["team2"], n, p1, p2, m.get("bestOf", 5))
             for m in FIXTURES["matches"] if m["status"] == "finished"
             for n, (p1, p2) in enumerate(m["sets"], 1)],
        ]
        with patch.object(backend, "get_db_connection", return_value=connection):
            result = backend.app.test_client().get("/api/standings")
        self.assertEqual([{k:v for k,v in row.items() if k not in {"teamId","logo"}} for row in result.json], FIXTURES["standings"])
        self.assertEqual(cursor.execute.call_args_list[0].args[0], "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")

    def test_malformed_score_containers(self):
        for sets in (None, {}, "sets", [None] * 3, [{}] * 3):
            self.assertIsInstance(backend.validate_sets(sets), str)
