"""Synthetic Web foundation security, persistence and private-path acceptance."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid

AVAILABLE = all(importlib.util.find_spec(name) for name in ("fastapi", "pwdlib", "httpx"))
if AVAILABLE:
    from fastapi.testclient import TestClient
    from wealth_ledger.web.api import create_app
    from wealth_ledger.web.auth import Auth, password_hash, ABSOLUTE_SECONDS, IDLE_SECONDS
    from wealth_ledger.web.config import WebSettings
    from wealth_ledger.web.storage import Store, prepare_instance, contained, WebError

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PASSWORD = "example-test-only-strong-password"
EXAMPLE_REPLACEMENT = "example-replacement-only-password"
ORIGIN = "http://localhost:8000"


@unittest.skipUnless(AVAILABLE, "Optional Web dependencies are not installed")
class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wealth-web-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "instance"
        self.settings = WebSettings(self.root)
        self.now = [1700000000.0]
        prepare_instance(self.settings)
        self.store = Store(self.settings, clock=lambda: self.now[0])
        self.store.set_owner("owner", password_hash(EXAMPLE_PASSWORD))
        self.app = create_app(self.settings, clock=lambda: self.now[0])
        self.client = TestClient(self.app, base_url=ORIGIN, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.csrf = None

    def bootstrap(self, client=None):
        client = client or self.client
        result = client.get("/api/v1/auth/csrf")
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()["csrf_token"]

    def login(self, client=None):
        client = client or self.client
        token = self.bootstrap(client)
        result = client.post("/api/v1/auth/login", headers={"Origin": ORIGIN, "X-CSRF-Token": token},
            json={"username": "owner", "password": EXAMPLE_PASSWORD})
        self.assertEqual(result.status_code, 200, result.text)
        if client is self.client:
            self.csrf = result.json()["csrf_token"]
        return result.json()["csrf_token"]

    def mutate(self, method, path, *, body=None, client=None, csrf=None, headers=None):
        client = client or self.client
        return client.request(method, path, json=body,
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf or self.csrf or "", **(headers or {})})

    def portfolio(self, name="Synthetic household"):
        response = self.mutate("POST", "/api/v1/portfolios", body={"name": name})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_no_http_owner_claim_and_private_routes_require_auth(self):
        for path in ("/api/v1/auth/session", "/api/v1/portfolios", "/api/v1/openapi.json",
                     "/api/v1/portfolios/" + "a"*32 + "/artifacts"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)
            self.assertIn("no-store", response.headers["cache-control"])
        for path in ("/docs", "/redoc", "/openapi.json", "/data/admin/app.sqlite3", "/secrets/csrf.key", "/api/v1/auth/register"):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get("/healthz").json(), {"status": "ready", "api_version": 1})

    def test_authenticated_openapi_has_typed_results_and_cookie_security(self):
        self.login()
        response = self.client.get("/api/v1/openapi.json")
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        self.assertEqual(schema["components"]["securitySchemes"]["OwnerSession"]["in"], "cookie")
        operation = schema["paths"]["/api/v1/portfolios"]["get"]
        self.assertEqual(operation["security"], [{"OwnerSession": []}])
        self.assertIn("PortfolioList", operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"])
        self.assertIn("ErrorView", operation["responses"]["401"]["content"]["application/json"]["schema"]["$ref"])

    def test_host_and_origin_are_exact_and_forwarded_headers_are_not_trusted(self):
        self.assertEqual(self.client.get("/healthz", headers={"Host": "attacker.test"}).status_code, 400)
        token = self.bootstrap()
        body = {"username": "owner", "password": EXAMPLE_PASSWORD}
        for origin in (None, "null", "http://attacker.test", ORIGIN + ".attacker.test"):
            headers = {"X-CSRF-Token": token, "X-Forwarded-Host": "localhost:8000"}
            if origin is not None:
                headers["Origin"] = origin
            result = self.client.post("/api/v1/auth/login", json=body, headers=headers)
            self.assertEqual(result.status_code, 403)
        self.assertEqual(self.client.post("/api/v1/auth/login", json=body,
            headers={"Origin": ORIGIN, "X-CSRF-Token": token, "X-Forwarded-For": "198.51.100.1"}).status_code, 200)

    def test_login_rotation_csrf_binding_cookie_flags_and_only_hashes_saved(self):
        token = self.bootstrap()
        old = self.client.cookies.get("wealth_session")
        self.login()
        current = self.client.cookies.get("wealth_session")
        self.assertNotEqual(old, current)
        self.assertIsNone(self.app.state.auth.session(old, authenticated=False))
        with closing(self.store.connect()) as conn:
            row = conn.execute("SELECT token_hash FROM sessions").fetchone()
            self.assertEqual(row[0], hashlib.sha256(current.encode()).hexdigest())
        self.assertNotIn(current.encode(), self.store.db.read_bytes())
        self.assertNotIn(EXAMPLE_PASSWORD.encode(), self.store.db.read_bytes())
        self.assertTrue(self.store.owner()["password_hash"].startswith("$argon2id$"))
        result = self.mutate("POST", "/api/v1/portfolios", body={"name": "Synthetic"}, csrf=token)
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.client.get("/api/v1/auth/session").status_code, 200)
        response = self.client.get("/api/v1/auth/csrf")
        self.assertEqual(response.json()["csrf_token"], self.csrf)
        other = TestClient(self.app, base_url=ORIGIN)
        self.addCleanup(other.close)
        other_token = self.bootstrap(other)
        self.assertEqual(self.mutate("POST", "/api/v1/portfolios", body={"name": "Synthetic"}, csrf=other_token).status_code, 403)
        fresh = TestClient(self.app, base_url=ORIGIN)
        self.addCleanup(fresh.close)
        cookie = fresh.get("/api/v1/auth/csrf").headers["set-cookie"].lower()
        self.assertIn("httponly", cookie); self.assertIn("samesite=lax", cookie); self.assertIn("path=/", cookie)

    def test_csrf_rejects_missing_or_forged_token_for_login_logout_and_settings(self):
        self.bootstrap()
        response = self.client.post("/api/v1/auth/login", json={"username": "owner", "password": EXAMPLE_PASSWORD}, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 403)
        self.login()
        portfolio = self.portfolio()
        for method, path in (("POST", "/api/v1/auth/logout"), ("PUT", f"/api/v1/portfolios/{portfolio}/settings")):
            result = self.client.request(method, path, headers={"Origin": ORIGIN, "X-CSRF-Token": "0"*64}, json={})
            self.assertEqual(result.status_code, 403)

    def test_polls_do_not_extend_idle_and_activity_does_not_extend_absolute_expiry(self):
        self.login()
        for _ in range(3):
            self.now[0] += 500
            self.assertEqual(self.client.get("/api/v1/auth/session").status_code, 200)
            self.assertEqual(self.client.get("/api/v1/portfolios").status_code, 200)
        self.now[0] += 300
        self.assertEqual(self.client.get("/api/v1/auth/session").status_code, 401)
        self.login()
        start = self.now[0]
        for _ in range(43):
            self.now[0] += 1000
            self.assertEqual(self.mutate("POST", "/api/v1/auth/activity").status_code, 204)
        self.now[0] = start + ABSOLUTE_SECONDS
        self.assertEqual(self.client.get("/api/v1/auth/session").status_code, 401)

    def test_logout_and_host_reset_revoke_sessions(self):
        self.login()
        old = self.client.cookies.get("wealth_session")
        self.assertEqual(self.mutate("POST", "/api/v1/auth/logout").status_code, 204)
        self.client.cookies.set("wealth_session", old)
        self.assertEqual(self.client.get("/api/v1/auth/session").status_code, 401)
        self.client.cookies.clear()
        self.login()
        self.store.set_owner(None, password_hash(EXAMPLE_REPLACEMENT), reset=True)
        self.assertEqual(self.client.get("/api/v1/auth/session").status_code, 401)

    def test_password_change_revokes_all_clients_and_hides_validation_input(self):
        self.login()
        other = TestClient(self.app, base_url=ORIGIN); self.addCleanup(other.close)
        self.login(other)
        result = self.mutate("POST", "/api/v1/auth/password", body={"current_password": EXAMPLE_PASSWORD, "new_password": EXAMPLE_REPLACEMENT})
        self.assertEqual(result.status_code, 204, result.text)
        self.assertEqual(other.get("/api/v1/auth/session").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/auth/session").status_code, 401)
        token = self.bootstrap()
        result = self.mutate("POST", "/api/v1/auth/login", csrf=token,
            body={"username": "owner", "password": EXAMPLE_REPLACEMENT, "unexpected": EXAMPLE_PASSWORD})
        self.assertEqual(result.status_code, 422)
        self.assertNotIn(EXAMPLE_PASSWORD, result.text)
        self.assertNotIn(EXAMPLE_REPLACEMENT, result.text)
        self.assertNotIn("unexpected", result.text)

    def test_login_limit_persists_and_does_not_trust_forwarded_ips(self):
        token = self.bootstrap()
        for index in range(5):
            result = self.mutate("POST", "/api/v1/auth/login", csrf=token,
                body={"username": "owner", "password": "example-wrong-password"},
                headers={"X-Forwarded-For": f"198.51.100.{index}"})
            self.assertEqual(result.status_code, 401)
        self.assertEqual(self.mutate("POST", "/api/v1/auth/login", csrf=token,
            body={"username": "owner", "password": EXAMPLE_PASSWORD}).status_code, 429)
        reloaded = create_app(self.settings, clock=lambda: self.now[0])
        self.assertEqual(reloaded.state.auth.store.owner()["username"], "owner")
        with self.assertRaises(WebError) as error:
            reloaded.state.auth.budget("login:" + reloaded.state.auth.peer_key("testclient"), 5, 900)
        self.assertEqual(error.exception.status, 429)
        self.now[0] += 901
        self.login()

    def test_password_hash_capacity_is_bounded(self):
        auth = self.app.state.auth
        with auth.hash_slot(), auth.hash_slot():
            with self.assertRaises(WebError) as error:
                with auth.hash_slot():
                    self.fail("A third password hash must not run concurrently")
        self.assertEqual(error.exception.status, 429)
        with auth.hash_slot():
            pass

    def test_anonymous_csrf_expiry_is_bounded(self):
        token = self.bootstrap()
        self.now[0] += 601
        result = self.mutate("POST", "/api/v1/auth/login", csrf=token, body={"username": "owner", "password": EXAMPLE_PASSWORD})
        self.assertEqual(result.status_code, 403)
        self.login()

    def test_portfolios_are_server_identified_and_do_not_initialize_financial_databases(self):
        self.login()
        first, second = self.portfolio(), self.portfolio("Another synthetic portfolio")
        self.assertNotEqual(first, second)
        response = self.client.get("/api/v1/portfolios").json()
        self.assertEqual(len(response["portfolios"]), 2)
        self.assertNotIn(str(self.root), json.dumps(response))
        for item in (first, second):
            project = self.root / "portfolios" / item
            self.assertFalse((project / "data/db/portfolio.sqlite3").exists())
            self.assertEqual(self.client.get(f"/api/v1/portfolios/{item}/settings").json(),
                {"locale": "en-CA", "btc_cost_policy": "actual_only"})
        self.assertEqual(self.mutate("POST", "/api/v1/portfolios", body={"name": "Synthetic", "workspace": "/tmp/untrusted"}).status_code, 422)
        self.assertEqual(self.client.get("/api/v1/portfolios/" + "f"*32).status_code, 404)

    def test_settings_preserve_other_sections_and_are_cli_compatible_and_persistent(self):
        self.login(); item = self.portfolio()
        path = self.root / "portfolios" / item / "config/local.toml"
        with path.open("a") as stream:
            stream.write('\n[other]\ncustom = "synthetic-preserved"\n')
        result = self.mutate("PUT", f"/api/v1/portfolios/{item}/settings",
            body={"locale": "zh-TW", "btc_cost_policy": "bull_average_proxy"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn('custom = "synthetic-preserved"', path.read_text())
        from wealth_ledger.workspace import resolve_workspace
        from wealth_ledger.application import ApplicationService
        from wealth_ledger.settings import report_locale, btc_cost_policy
        workspace = resolve_workspace(explicit=path.parent.parent)
        self.assertEqual(report_locale(workspace.workspace_root), "zh-TW")
        self.assertEqual(btc_cost_policy(workspace.workspace_root), "bull_average_proxy")
        self.assertEqual(ApplicationService(workspace).operations(), [])
        fresh = Store(self.settings)
        self.assertEqual(fresh.reporting_settings(item)["locale"], "zh-TW")
        self.assertEqual(self.mutate("PUT", f"/api/v1/portfolios/{item}/settings",
            body={"locale": "unknown", "btc_cost_policy": "actual_only"}).status_code, 422)
        self.assertFalse((workspace.workspace_root / "data/db/portfolio.sqlite3").exists())

    def test_settings_honor_existing_cli_lock(self):
        self.login(); item = self.portfolio()
        project = self.root / "portfolios" / item
        (project / "work").mkdir()
        (project / "work/update.lock").write_text("synthetic owner")
        original = (project / "config/local.toml").read_bytes()
        response = self.mutate("PUT", f"/api/v1/portfolios/{item}/settings",
            body={"locale": "zh-TW", "btc_cost_policy": "actual_only"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual((project / "config/local.toml").read_bytes(), original)

    def test_missing_instance_key_is_not_silently_regenerated(self):
        key = self.root / "secrets/csrf.key"
        key.unlink()
        with self.assertRaises(ValueError):
            prepare_instance(self.settings)
        self.assertFalse(key.exists())

    def test_invalid_settings_fail_closed_without_overwrite(self):
        self.login(); item = self.portfolio()
        path = self.root / "portfolios" / item / "config/local.toml"
        path.write_text('reporting = {locale="zh-TW", btc_cost_policy="actual_only"}\n')
        before = path.read_bytes()
        self.assertEqual(self.mutate("PUT", f"/api/v1/portfolios/{item}/settings",
            body={"locale": "en-CA", "btc_cost_policy": "actual_only"}).status_code, 409)
        self.assertEqual(path.read_bytes(), before)

    def test_artifacts_are_scoped_hashed_private_and_not_public_static(self):
        self.login(); first, second = self.portfolio(), self.portfolio()
        report = self.root / "portfolios" / first / "reports/synthetic/report.md"
        report.parent.mkdir(parents=True); report.write_bytes(b"Synthetic report bytes")
        artifact = self.store.register_artifact(first, uuid.uuid4().hex, "reports/synthetic/report.md")
        path = f"/api/v1/portfolios/{first}/artifacts/{artifact}"
        self.assertEqual(self.client.get(path).content, b"Synthetic report bytes")
        self.assertEqual(self.client.get(f"/api/v1/portfolios/{second}/artifacts/{artifact}").status_code, 404)
        anonymous = TestClient(self.app, base_url=ORIGIN); self.addCleanup(anonymous.close)
        self.assertEqual(anonymous.get(path).status_code, 401)
        response = self.client.get(path)
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertNotIn("relative_path", self.client.get(f"/api/v1/portfolios/{first}/artifacts").text)
        report.write_bytes(b"Tampered synthetic report")
        self.assertEqual(self.client.get(path).status_code, 409)

    @unittest.skipUnless(os.name == "posix", "Symlink acceptance needs POSIX")
    def test_traversal_symlinks_and_foreign_ownership_fail_closed(self):
        self.login(); item = self.portfolio()
        project = self.root / "portfolios" / item
        for path in ("../outside", "/absolute", "reports/../../secrets/csrf.key", "reports/./file", "reports\\file"):
            with self.assertRaises(WebError):
                contained(project, path)
        (project / "reports").symlink_to(self.root / "secrets", target_is_directory=True)
        with self.assertRaises(WebError):
            self.store.register_artifact(item, uuid.uuid4().hex, "reports/csrf.key")
        with closing(sqlite3.connect(self.store.db)) as conn:
            conn.execute("UPDATE portfolios SET owner_id=999 WHERE id=?", (item,)); conn.commit()
        self.assertEqual(self.client.get(f"/api/v1/portfolios/{item}").status_code, 404)

    def test_request_limits_and_public_error_redaction(self):
        self.login()
        result = self.client.post("/api/v1/portfolios", content=b"x"*17000,
            headers={"Origin": ORIGIN, "X-CSRF-Token": self.csrf, "Content-Type": "application/json"})
        self.assertEqual(result.status_code, 413)
        result = self.client.post("/api/v1/portfolios", content=iter([b"x"*10000, b"x"*10000]),
            headers={"Origin": ORIGIN, "X-CSRF-Token": self.csrf, "Content-Type": "application/json"})
        self.assertEqual(result.status_code, 413)
        response = self.client.get("/api/v1/auth/session")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(response.headers["x-frame-options"], "DENY")

    def test_secure_cookie_and_configuration_fail_closed(self):
        configured = WebSettings(self.root, "https://ledger.example.test")
        app = create_app(configured)
        with TestClient(app, base_url="https://ledger.example.test") as client:
            response = client.get("/api/v1/auth/csrf")
            cookie = response.headers["set-cookie"].lower()
            self.assertIn("__host-wealth_session=", cookie)
            self.assertIn("secure", cookie); self.assertNotIn("domain=", cookie)
            self.assertIn("strict-transport-security", response.headers)
        for origin in ("http://ledger.example.test", "https://" + "owner:" + "example-secret@ledger.example.test", "http://localhost:8000/path", "http://localhost:8000/"):
            with self.assertRaises(ValueError):
                WebSettings(self.root, origin)
        for root in (Path("relative"), Path.home(), ROOT, ROOT / "work/private-instance"):
            with self.assertRaises(ValueError):
                WebSettings(root)

    def test_uninitialized_or_future_schema_cannot_be_claimed_by_http(self):
        empty = WebSettings(self.root.parent / "fresh")
        with self.assertRaises(ValueError):
            create_app(empty)
        prepare_instance(empty)
        with self.assertRaises(ValueError):
            create_app(empty)
        with closing(sqlite3.connect(self.store.db)) as conn:
            conn.execute("PRAGMA user_version=999")
        with self.assertRaises(ValueError):
            prepare_instance(self.settings)
        with self.assertRaises(ValueError):
            Store(self.settings)
        self.assertFalse((self.root / "data/db/portfolio.sqlite3").exists())

    def test_native_server_restart_preserves_session_and_settings(self):
        from test_web_docker import free_port, http_client, request_json, wait_ready
        port = free_port(); origin = f"http://localhost:{port}"
        command = [sys.executable, str(ROOT / "scripts/web.py"), "--data-root", str(self.root),
                   "--public-origin", origin, "serve", "--port", str(port)]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        process = None
        try:
            process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_ready(origin, process)
            client = http_client()
            csrf = request_json(client, origin, "/api/v1/auth/csrf")["csrf_token"]
            csrf = request_json(client, origin, "/api/v1/auth/login", {"username": "owner", "password": EXAMPLE_PASSWORD}, csrf)["csrf_token"]
            portfolio = request_json(client, origin, "/api/v1/portfolios", {"name": "Synthetic native process"}, csrf)["id"]
            expected = {"locale": "zh-CN", "btc_cost_policy": "bull_average_proxy"}
            request_json(client, origin, f"/api/v1/portfolios/{portfolio}/settings", expected, csrf, "PUT")
            process.terminate(); process.wait(timeout=5)
            process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_ready(origin, process)
            self.assertTrue(request_json(client, origin, "/api/v1/auth/session")["authenticated"])
            self.assertEqual(request_json(client, origin, f"/api/v1/portfolios/{portfolio}/settings"), expected)
        finally:
            if process and process.poll() is None:
                process.terminate(); process.wait(timeout=5)

    def test_host_cli_initialization_and_reset_keep_passwords_out_of_output(self):
        root = self.root.parent / "cli-instance"
        command = [sys.executable, str(ROOT / "scripts/web.py"), "--data-root", str(root)]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        response = subprocess.run([*command, "init-owner", "--password-stdin"], input=EXAMPLE_PASSWORD+"\n", capture_output=True, text=True, env=env)
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertNotIn(EXAMPLE_PASSWORD, response.stdout+response.stderr)
        second = subprocess.run([*command, "init-owner", "--password-stdin"], input=EXAMPLE_PASSWORD+"\n", capture_output=True, text=True, env=env)
        self.assertNotEqual(second.returncode, 0)
        response = subprocess.run([*command, "reset-password", "--password-stdin"], input=EXAMPLE_REPLACEMENT+"\n", capture_output=True, text=True, env=env)
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertNotIn(EXAMPLE_REPLACEMENT, response.stdout+response.stderr)


class OptionalDependencyBoundaryTests(unittest.TestCase):
    def test_financial_services_import_without_optional_web_dependencies(self):
        code = """import sys
class BlockWeb:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'fastapi','starlette','pydantic','pwdlib','uvicorn'}:
            raise AssertionError('Financial CLI imported optional API dependency')
sys.meta_path.insert(0, BlockWeb())
import wealth_ledger.core, wealth_ledger.workflow, wealth_ledger.application
import wealth_ledger.reporting, wealth_ledger.workbook
"""
        response = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
            env={**os.environ, 'PYTHONPATH': str(ROOT/'src'), 'PYTHONDONTWRITEBYTECODE':'1'})
        self.assertEqual(response.returncode, 0, response.stderr)


if __name__ == "__main__":
    unittest.main()
