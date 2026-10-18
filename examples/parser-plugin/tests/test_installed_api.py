"""Optional installed API/isolated-worker acceptance using standard-library HTTP."""
import http.cookiejar
import importlib.util
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from test_synthetic_parser import fixture

WEB = all(importlib.util.find_spec(name) for name in ("fastapi", "pwdlib", "uvicorn", "huey"))


@unittest.skipUnless(WEB, "Optional Web dependencies are not installed")
class InstalledApiTests(unittest.TestCase):
    def test_cli_and_api_worker_share_installed_plugin_without_booking(self):
        from wealth_ledger.source_pipeline import plan_sources
        from wealth_ledger.web.auth import password_hash
        from wealth_ledger.web.config import WebSettings
        from wealth_ledger.web.jobs import Jobs
        from wealth_ledger.web.storage import Store, prepare_instance
        from wealth_ledger.web.worker import execute_isolated
        from wealth_ledger.operations import fingerprint
        with tempfile.TemporaryDirectory(prefix="synthetic-plugin-api-") as directory:
            root = Path(directory).resolve()
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            origin = f"http://localhost:{port}"
            settings = WebSettings(root / "instance", origin)
            prepare_instance(settings)
            store = Store(settings)
            supplied = secrets.token_urlsafe(32)
            store.set_owner("owner", password_hash(supplied))
            config = settings.data_root / "admin/source-parsers.json"
            config.write_text(json.dumps({"schema_version":1, "enabled":[{"distribution":"wealth-ledger-synthetic-parser",
                "version":"0.1.0", "entry_point":"synthetic", "adapter_id":"synthetic.holdings"}], "bindings":[]}))
            raw = fixture()
            source = root / "invented.csv"; source.write_bytes(raw)
            expected = plan_sources([source], config_path=config)
            client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            def request(path, *, body=None, headers=None, params=""):
                encoded = json.dumps(body).encode() if body is not None and not isinstance(body, bytes) else body
                base = {"Origin":origin}
                if body is not None and not isinstance(body, bytes):
                    base["Content-Type"] = "application/json"
                req = urllib.request.Request(origin + path + params, data=encoded, headers={**base, **(headers or {})})
                with client.open(req, timeout=60) as response:
                    return response.status, json.load(response)
            program = ("import sys; from pathlib import Path; import uvicorn; "
                       "from wealth_ledger.web.api import create_app; from wealth_ledger.web.config import WebSettings; "
                       "uvicorn.run(create_app(WebSettings(Path(sys.argv[1]),sys.argv[2])),host='127.0.0.1',port=int(sys.argv[3]),log_level='error')")
            process = subprocess.Popen([sys.executable, "-c", program, str(settings.data_root), origin, str(port)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    try:
                        request("/healthz"); break
                    except OSError:
                        if process.poll() is not None:
                            self.fail("Synthetic API exited before readiness")
                        time.sleep(0.1)
                else:
                    self.fail("Synthetic API readiness timeout")
                csrf = request("/api/v1/auth/csrf")[1]["csrf_token"]
                headers = {"X-CSRF-Token":csrf}
                status, body = request("/api/v1/auth/login", headers=headers, body={"username":"owner", "password":supplied})
                self.assertEqual(status, 200)
                headers["X-CSRF-Token"] = body["csrf_token"]
                pid = request("/api/v1/portfolios", headers=headers, body={"name":"Synthetic plugin acceptance"})[1]["id"]
                prefix = "/api/v1/portfolios/" + pid
                _, project = store.portfolio(pid)
                before = fingerprint(project)
                status, body = request(prefix + "/uploads", params="?kind=source_csv&filename=invented.csv",
                    headers={**headers,"Content-Type":"text/csv"}, body=raw)
                self.assertEqual(status, 201)
                status, job = request(prefix + "/source-plans", headers={**headers,"Idempotency-Key":"synthetic-installed-plan"},
                    body={"upload_ids":[body["id"]]})
                self.assertEqual(status, 202)
                self.assertEqual(execute_isolated(settings, job["id"]), 0)
                row = Jobs(store).get(pid, job["id"])
                self.assertEqual(row["status"], "ready", row["error_code"])
                self.assertEqual(json.loads(row["result_json"]), expected)
                self.assertEqual(fingerprint(project), before)
                self.assertFalse((project / "data/db/portfolio.sqlite3").exists())
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    request(prefix + "/jobs", headers={**headers,"Idempotency-Key":"synthetic-cannot-book"},
                        body={"preview_id":job["id"]})
                self.assertEqual(caught.exception.code, 404)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=10)
