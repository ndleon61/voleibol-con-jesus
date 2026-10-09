import os
import hashlib
from pathlib import Path
import secrets
import shutil
import tempfile
import unittest
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from backup import backup, restore, run, restore_empty, database_fingerprint


class BackupSafetyTests(unittest.TestCase):
    def test_credentials_never_enter_subprocess_arguments(self):
        with patch("backup.subprocess.run") as process:
            process.return_value.returncode=0
            run(["pg_restore","sample.dump"],"dbname=test host=example user=test password=private")
        args=process.call_args.args[0]
        self.assertNotIn("private"," ".join(args))
        self.assertIn("host=example"," ".join(args))
        self.assertEqual(process.call_args.kwargs["env"]["PGPASSWORD"],"private")

    def test_restore_never_accepts_existing_application_database_name(self):
        with self.assertRaises(ValueError): restore("/tmp/unused","dbname=voleibolcuba","voleibolcuba","/tmp/unused")


@unittest.skipUnless(os.environ.get("AUTH_TEST_DATABASE_URL") and shutil.which("pg_dump") and shutil.which("pg_restore"),"PostgreSQL y herramientas de copia no configurados")
class BackupRoundTripTests(unittest.TestCase):
    def test_database_and_logos_round_trip_into_isolated_database(self):
        database=os.environ["AUTH_TEST_DATABASE_URL"]
        name="voli_restore_test_"+secrets.token_hex(8)
        target=make_conninfo(database,dbname=name)
        def drop():
            with psycopg.connect(make_conninfo(database,dbname="postgres"),autocommit=True) as conn:
                conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        self.addCleanup(drop)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);logos=root/"logos";logos.mkdir()
            filename="a"*32+".webp"
            (logos/filename).write_bytes(b"logo fixture preserved byte for byte")
            # Snapshot the real database read-only, restore only to a new database.
            with psycopg.connect(database) as conn:
                tables=conn.execute("SELECT table_schema,table_name FROM information_schema.tables WHERE table_type='BASE TABLE' AND table_schema NOT IN('pg_catalog','information_schema') AND table_schema NOT LIKE '%test_%' ORDER BY 1,2").fetchall()
                queries={tuple(row):sql.SQL("SELECT * FROM {}.{} ORDER BY 1").format(sql.Identifier(row[0]),sql.Identifier(row[1])) for row in tables if row[1] not in {"administrator_sessions","administrator_login_attempts"}}
                def snapshot(connection):
                    return {key:hashlib.sha256(repr(sorted(map(repr,connection.execute(query).fetchall()))).encode()).hexdigest() for key,query in queries.items()}
                before=snapshot(conn)
            destination=root/"backup"
            backup(database,logos,destination)
            self.assertEqual(destination.stat().st_mode & 0o777,0o700)
            self.assertEqual((destination/"database.dump").stat().st_mode & 0o777,0o600)
            restore(destination,database,name,root/"restored-logos")
            with psycopg.connect(target) as conn:
                after=snapshot(conn)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM administrator_sessions").fetchone()[0],0)
            self.assertEqual(before,after)
            self.assertEqual((root/"restored-logos"/filename).read_bytes(),(logos/filename).read_bytes())
            managed_name = "voli_staging_test_" + secrets.token_hex(8)
            managed_target = make_conninfo(database, dbname=managed_name, sslmode="verify-full")
            with psycopg.connect(make_conninfo(database, dbname="postgres"), autocommit=True) as conn:
                conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(managed_name)))
            def drop_managed():
                with psycopg.connect(make_conninfo(database, dbname="postgres"), autocommit=True) as conn:
                    conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(managed_name)))
            self.addCleanup(drop_managed)
            # Unix socket fixture tests managed restore safety, not remote TLS.
            restore_empty(destination, managed_target, managed_name)
            self.assertEqual(database_fingerprint(database), database_fingerprint(managed_target))
            with self.assertRaises(ValueError): restore_empty(destination, managed_target, managed_name)
            # Reusing a target is rejected, never overwritten.
            with self.assertRaises(psycopg.errors.DuplicateDatabase): restore(destination,database,name,root/"another-logo-dir")
            with psycopg.connect(database) as conn:
                self.assertEqual(snapshot(conn),before)
            (destination/"logos.tar.gz").write_bytes(b"corrupted")
            with self.assertRaises(ValueError): restore(destination,database,name,root/"bad")
