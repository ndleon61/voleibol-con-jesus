from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_auth as auth_tests
import app as backend
import teams
import psycopg
from PIL import Image


def logo_bytes(format="PNG", size=(20, 20)):
    output = BytesIO()
    Image.new("RGB", size, color="red").save(output, format=format)
    return output.getvalue()


class TeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth_tests.AuthenticationTests.setUpClass()

    def setUp(self):
        self.auth = auth_tests.AuthenticationTests()
        self.auth.setUp()
        self.addCleanup(self.auth.tearDown)
        self.client = self.auth.client
        self.rows = {1: (1, "Los Lobos", "/media/los_lobos.JPG")}
        self.associated = set()
        self.counter = 2
        self.auth.connection.execute.side_effect = self.execute
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        config_patch = patch.dict(backend.app.config, TEAM_LOGO_DIRECTORY=self.directory.name)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        self.assertEqual(self.auth.login().status_code, 303)
        self.headers = {"X-CSRF-Token": self.auth.session_token()}

    def execute(self, query, args=None):
        result = None
        if query.startswith("SELECT t.id, t.name, t.logo_path FROM tournament_team_identities"):
            return SimpleNamespace(fetchall=lambda: list(self.rows.values()))
        if query.startswith("SELECT t.id, t.name, t.logo_path"):
            return SimpleNamespace(fetchall=lambda: [(*row, row[0] in self.associated) for row in self.rows.values()])
        if query.startswith("SELECT id, name, logo_path FROM teams WHERE"):
            result = self.rows.get(args[0])
        elif query.startswith("INSERT INTO teams") or query.startswith("UPDATE teams SET name"):
            name, logo = args[:2]
            team_id = args[2] if len(args) > 2 else self.counter
            if any(row[1].lower().strip() == name.lower().strip() and row[0] != team_id for row in self.rows.values()):
                raise psycopg.errors.UniqueViolation("duplicate team")
            result = (team_id, name, logo)
            self.rows[team_id] = result
            self.counter += 1
        elif query.startswith("SELECT EXISTS (SELECT 1 FROM matches"):
            result = (args[0] in self.associated,)
        elif query.startswith("DELETE FROM teams"):
            self.rows.pop(args[0], None)
        else:
            return self.auth.execute(query, args)
        return SimpleNamespace(fetchone=lambda: result)

    def create(self, name="Nuevo equipo", logo=None, filename="logo.png"):
        data = {"name": name}
        if logo is not None:
            data["logo"] = (BytesIO(logo), filename)
        return self.client.post("/api/admin/teams", data=data, headers=self.headers)

    def test_public_and_private_listing(self):
        response = backend.app.test_client().get("/api/teams")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, [{"id": 1, "name": "Los Lobos", "logo": "/media/los_lobos.JPG"}])
        self.associated.add(1)
        self.assertTrue(self.client.get("/api/admin/teams").json[0]["has_matches"])

    def test_create_without_logo_and_parameterized_name(self):
        response = self.create("  Equipo   de O'Brien  ")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["team"]["name"], "Equipo de O'Brien")
        self.assertEqual(response.json["team"]["logo"], "")

    def test_required_and_long_names(self):
        for name in ("", "   ", "A" * 101, "Equipo\x00"):
            self.assertEqual(self.create(name).status_code, 400)
        self.assertEqual(len(self.rows), 1)

    def test_duplicate_names_create_and_edit(self):
        self.assertEqual(self.create(" los lobos ").status_code, 409)
        created = self.create().json["team"]
        response = self.client.put(f'/api/admin/teams/{created["id"]}',
                                   json={"name": "LOS LOBOS"}, headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.rows[created["id"]][1], "Nuevo equipo")

    def test_rename_keeps_team_id_and_existing_logo(self):
        self.associated.add(1)
        response = self.client.put("/api/admin/teams/1", json={"name": "Los Lobos Nuevos"}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["team"]["id"], 1)
        self.assertEqual(response.json["team"]["logo"], "/media/los_lobos.JPG")
        self.assertIn(1, self.associated)

    def test_valid_images_reencoded_and_publicly_served(self):
        for format in ("JPEG", "PNG", "WEBP"):
            with self.subTest(format=format):
                response = self.create("Equipo " + format, logo_bytes(format), "../../unsafe.php")
                self.assertEqual(response.status_code, 201)
                url = response.json["team"]["logo"]
                self.assertRegex(url, r"^/team-logos/[a-f0-9]{32}\.webp$")
                image = backend.app.test_client().get(url)
                self.assertEqual(image.status_code, 200)
                self.assertEqual(image.content_type, "image/webp")
                with Image.open(BytesIO(image.data)) as decoded:
                    self.assertEqual(decoded.format, "WEBP")
                image.close()

    def test_invalid_uploads_and_size_limit(self):
        for data in (b"<svg><script>bad</script></svg>", b"not an image", logo_bytes("GIF"), b"", b"x" * (teams.MAX_LOGO_BYTES + 1)):
            self.assertEqual(self.create(logo=data).status_code, 400)
        response = self.client.post("/api/admin/teams", data=b"x" * (teams.MAX_LOGO_BYTES + 65537),
                                    content_type="application/octet-stream", headers=self.headers)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_pixel_limit_and_corrupt_image(self):
        with patch.object(teams, "MAX_LOGO_PIXELS", 100):
            self.assertEqual(self.create(logo=logo_bytes()).status_code, 400)
        self.assertEqual(self.create(logo=logo_bytes()[:40]).status_code, 400)

    def test_replace_remove_and_rollback_logo_files(self):
        created = self.create(logo=logo_bytes()).json["team"]
        old = Path(self.directory.name) / created["logo"].split("/")[-1]
        self.assertTrue(old.exists())
        response = self.client.put(f'/api/admin/teams/{created["id"]}',
                                   data={"name": "Nuevo equipo", "logo": (BytesIO(logo_bytes()), "logo.png")}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(old.exists())
        current = Path(self.directory.name) / response.json["team"]["logo"].split("/")[-1]
        self.assertEqual(self.create("Los Lobos", logo=logo_bytes()).status_code, 409)
        self.assertEqual(set(Path(self.directory.name).iterdir()), {old,current})
        response = self.client.put(f'/api/admin/teams/{created["id"]}',
                                   json={"name": "Nuevo equipo", "remove_logo": True}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["team"]["logo"], "")
        self.assertTrue(current.exists())

    def test_delete_without_matches_retains_immutable_logo(self):
        team = self.create(logo=logo_bytes()).json["team"]
        response = self.client.delete(f'/api/admin/teams/{team["id"]}', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(team["id"], self.rows)
        self.assertTrue((Path(self.directory.name)/team["logo"].rsplit("/",1)[1]).exists())

    def test_delete_with_matches_preserves_history(self):
        self.associated.add(1)
        response = self.client.delete("/api/admin/teams/1", headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertIn("partidos registrados", response.json["error"])
        self.assertIn(1, self.rows)
        self.assertIn(1, self.associated)

    def test_missing_team(self):
        self.assertEqual(self.client.put("/api/admin/teams/999", json={"name": "Equipo"}, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.delete("/api/admin/teams/999", headers=self.headers).status_code, 404)

    def test_unauthorized_and_csrf_failures(self):
        anonymous = backend.app.test_client()
        for method, path in (("get", "/api/admin/teams"), ("post", "/api/admin/teams"),
                             ("put", "/api/admin/teams/1"), ("delete", "/api/admin/teams/1")):
            self.assertEqual(getattr(anonymous, method)(path).status_code, 401)
        for method, path in (("post", "/api/admin/teams"), ("put", "/api/admin/teams/1"), ("delete", "/api/admin/teams/1")):
            self.assertEqual(getattr(self.client, method)(path, json={"name": "Equipo"}).status_code, 403)
        self.assertEqual(len(self.rows), 1)

    def test_upload_route_does_not_expose_arbitrary_files(self):
        self.assertEqual(self.client.get("/team-logos/auth.py").status_code, 404)
        self.assertEqual(self.client.get("/team-logos/../../app.py").status_code, 404)

    def test_uploaded_symlink_cannot_expose_local_files(self):
        path=Path(self.directory.name)/("a"*32+".webp")
        path.symlink_to(Path(__file__).resolve())
        self.assertEqual(self.client.get("/team-logos/"+path.name).status_code,404)

    def test_filename_collision_does_not_delete_existing_logo(self):
        path=Path(self.directory.name)/("a"*32+".webp")
        path.write_bytes(b"existing logo")
        with patch("teams.secrets.token_hex",return_value="a"*32), self.assertLogs(backend.app.logger,level="ERROR"):
            response=self.create(logo=logo_bytes())
        self.assertEqual(response.status_code,500)
        self.assertEqual(path.read_bytes(),b"existing logo")
        self.assertEqual(len(self.rows),1)


if __name__ == "__main__":
    unittest.main()
