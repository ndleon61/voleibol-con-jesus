import unittest
from unittest.mock import MagicMock, patch

from neon_preflight import main, preflight, TARGET


class NeonPreflightTests(unittest.TestCase):
    host = "ep-staging.example.neon.tech"
    role = "voli_maintenance"

    def database(self, **changes):
        values = dict(host=self.host, dbname=TARGET, user=self.role,
                      sslmode="verify-full", sslrootcert="system", channel_binding="require")
        values.update(changes)
        return " ".join(f"{key}={value}" for key,value in values.items())

    def connection(self, connect):
        conn = connect.return_value.__enter__.return_value
        conn.info.host = self.host
        conn.pgconn.ssl_in_use = True
        conn.execute.return_value.fetchone.side_effect = [(TARGET,180006,"on",self.role), (False,), (True,True,True,True)]
        return conn

    def test_success_is_read_only_bounded_and_rolled_back(self):
        with patch("neon_preflight.psycopg.connect") as connect:
            conn = self.connection(connect)
            result = preflight(self.database(), self.host, self.role)
            self.assertTrue(result["vacia"])
            self.assertTrue(result["ssl_verificado"])
            self.assertIn("default_transaction_read_only=on", connect.call_args.kwargs["options"])
            self.assertEqual(connect.call_args.kwargs["connect_timeout"], 5)
            for call in conn.execute.call_args_list:
                self.assertTrue(call.args[0].startswith(("SELECT", "SET TRANSACTION READ ONLY")))
            conn.rollback.assert_called_once()

    def test_invalid_identity_ssl_pooler_or_role_rejected_before_connect(self):
        for changes in ({"dbname":"voleibolcuba"}, {"host":"ep-staging-pooler.example.neon.tech"},
                        {"user":"voli_runtime"}, {"sslmode":"require"},
                        {"sslrootcert":"missing"}, {"channel_binding":"prefer"}):
            with self.subTest(changes=changes), patch("neon_preflight.psycopg.connect") as connect:
                with self.assertRaises(ValueError): preflight(self.database(**changes), self.host, self.role)
                connect.assert_not_called()

    def test_wrong_server_identity_version_or_read_only_is_rejected(self):
        for identity in (("wrong",180006,"on",self.role), (TARGET,170011,"on",self.role),
                         (TARGET,180005,"on",self.role), (TARGET,190000,"on",self.role),
                         (TARGET,180006,"off",self.role), (TARGET,180006,"on","wrong")):
            with self.subTest(identity=identity), patch("neon_preflight.psycopg.connect") as connect:
                conn = self.connection(connect)
                conn.execute.return_value.fetchone.side_effect = [identity]
                with self.assertRaises(ValueError): preflight(self.database(), self.host, self.role)

    def test_nonempty_target_and_missing_permissions_are_rejected(self):
        for responses in ([(TARGET,180006,"on",self.role),(True,)],
                          [(TARGET,180006,"on",self.role),(False,),(True,True,False,False)]):
            with self.subTest(responses=responses), patch("neon_preflight.psycopg.connect") as connect:
                conn = self.connection(connect)
                conn.execute.return_value.fetchone.side_effect = responses
                with self.assertRaises(ValueError): preflight(self.database(), self.host, self.role)

    def test_ssl_must_actually_be_in_use(self):
        with patch("neon_preflight.psycopg.connect") as connect:
            conn = self.connection(connect)
            conn.pgconn.ssl_in_use = False
            with self.assertRaises(ValueError): preflight(self.database(), self.host, self.role)
            conn.execute.assert_not_called()

    def test_cli_requires_explicit_approval_before_any_connection(self):
        with patch("sys.argv", ["neon_preflight.py"]), patch("neon_preflight.preflight") as check, patch("sys.stderr"):
            with self.assertRaises(SystemExit): main()
            check.assert_not_called()
