import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from heartdevspace.core import Manager, normalize_domain, read_json, write_json
from heartdevspace.server import Dashboard, existing_dashboard


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.manager = Manager(self.home / "settings")
        self.project = self.home / "project with spaces"
        self.project.mkdir()

    def payload(self):
        return {"domain": "https://dev.example.com/", "tunnel_name": "test-pc",
                "allowed_roots": [str(self.project)], "port": 17776, "metrics_port": 20259}


class ConfigTests(Fixture):
    def test_domain_normalization(self):
        self.assertEqual(normalize_domain("HTTPS://DEV.EXAMPLE.COM/"), "dev.example.com")

    def test_bad_domains(self):
        for domain in ("http://dev.example.com", "https://dev.example.com/mcp", "127.0.0.1", "a..com", "https://x:y@dev.example.com", "dev.example.com\ncommands", "https://dev.example.com:443"):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                normalize_domain(domain)

    def test_password_persists_across_settings_changes(self):
        self.manager.save(self.payload())
        first = self.manager.owner_password()
        self.assertGreaterEqual(len(first), 32)
        changed = self.payload() | {"domain": "other.example.com"}
        self.manager.save(changed)
        self.assertEqual(first, self.manager.owner_password())
        self.assertNotIn(first, json.dumps(self.manager.snapshot()))
        self.assertEqual(read_json(self.manager.home / "devspace/config.json")["allowedRoots"], [str(self.project.resolve())])

    def test_reject_missing_directory_without_mutation(self):
        original = dict(self.manager.settings)
        with self.assertRaises(ValueError):
            self.manager.save(self.payload() | {"allowed_roots": [str(self.home / "missing")]})
        self.assertEqual(original, self.manager.settings)

    def test_duplicate_ports_and_running_change(self):
        with self.assertRaises(ValueError):
            self.manager.save(self.payload() | {"port": 20259})
        self.manager.settings["enabled"] = True
        with self.assertRaises(ValueError):
            self.manager.save(self.payload())

    def test_tunnel_yaml_quotes_path(self):
        self.manager.save(self.payload())
        self.manager.settings.update(tunnel_id="11111111-1111-4111-8111-111111111111", credentials_path=r"C:\User Files\my tunnel.json")
        self.manager.write_service_config()
        text = (self.manager.home / "tunnel.yml").read_text()
        self.assertIn('protocol: http2', text)
        self.assertIn(json.dumps(self.manager.settings["credentials_path"]), text)
        self.assertIn('http://127.0.0.1:17776', text)

    def test_existing_tunnel_routes_dns_without_overwrite(self):
        self.manager.save(self.payload())
        tunnel_id = "11111111-1111-4111-8111-111111111111"
        credential = self.home / ".cloudflared" / (tunnel_id + ".json")
        write_json(credential, {})
        self.manager.settings["cloudflared_path"] = "cloudflared.exe"
        with patch("heartdevspace.core.Path.home", return_value=self.home), patch("heartdevspace.core.hidden_run") as run:
            run.side_effect = [json.dumps([{"id": tunnel_id, "name": "test-pc", "deleted_at": "0001-01-01T00:00:00Z"}]), "OK"]
            self.manager.perform("tunnel_create")
            self.assertEqual(run.call_count, 2)
            route = run.call_args.args[0]
            self.assertEqual(route[-5:], ["tunnel", "route", "dns", tunnel_id, "dev.example.com"])
            self.assertNotIn("--overwrite-dns", route)

    def test_failed_start_rolls_back_enabled_state(self):
        self.manager.save(self.payload())
        credential = self.home / "fixture.json"
        write_json(credential, {})
        self.manager.settings.update(tunnel_id="test", credentials_path=str(credential))
        with patch.object(self.manager, "ensure_engine"), patch("heartdevspace.core.socket.socket") as sock, patch.object(self.manager, "control", side_effect=RuntimeError("task denied")):
            sock.return_value.__enter__.return_value.connect_ex.return_value = 1
            with self.assertRaisesRegex(RuntimeError, "task denied"):
                self.manager.perform("start")
        self.assertFalse(self.manager.settings["enabled"])
        self.assertFalse(read_json(self.manager.path)["enabled"])


class ApiTests(Fixture):
    def setUp(self):
        super().setUp()
        self.server = Dashboard(self.manager)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, **extra):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Cookie": f"{self.server.cookie_name}={self.server.session}", "X-Heart-Session": self.server.session,
                   "Origin": self.server.origin, "Content-Type": "application/json"}
        headers.update(extra)
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        code, data = response.status, response.read()
        connection.close()
        return code, data

    def test_unauthorized_and_cross_origin_rejected(self):
        self.assertEqual(self.request("GET", "/api/state", Cookie="")[0], 403)
        self.assertEqual(self.request("GET", "/api/state", Host="evil.example")[0], 403)
        self.assertEqual(self.request("POST", "/api/settings", self.payload(), Origin="https://evil.example")[0], 403)
        self.assertEqual(self.request("POST", "/api/settings", self.payload(), **{"X-Heart-Session": "bad"})[0], 403)

    def test_settings_and_explicit_password_reveal(self):
        self.assertEqual(self.request("POST", "/api/settings", self.payload())[0], 200)
        code, data = self.request("GET", "/api/state")
        self.assertEqual(code, 200)
        self.assertNotIn(self.manager.owner_password().encode(), data)
        code, data = self.request("POST", "/api/owner-password", {})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data)["password"], self.manager.owner_password())

    def test_static_allowlist_and_bad_json_shape(self):
        self.assertEqual(self.request("GET", "/../settings.json")[0], 404)
        self.assertEqual(self.request("POST", "/api/settings", [1])[0], 400)

    def test_reuse_verifies_live_session_and_home(self):
        url = self.server.origin + "/?key=" + self.server.session
        write_json(self.manager.home / "dashboard.json", {"url": url})
        self.assertEqual(existing_dashboard(self.manager.home), url)
        write_json(self.manager.home / "dashboard.json", {"url": url.replace(self.server.session, "0" * 64)})
        self.assertIsNone(existing_dashboard(self.manager.home))


if __name__ == "__main__":
    unittest.main()
