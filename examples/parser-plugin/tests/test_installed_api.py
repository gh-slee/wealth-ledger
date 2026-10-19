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


class InstalledV2ReportTests(unittest.TestCase):
    def test_actual_installed_third_parser_cli_generates_and_recovers_reports(self):
        from synthetic_parser.v2 import VERSION
        from wealth_ledger.source_valuation import read_observations
        from wealth_ledger.publishing import verify_bundle
        from wealth_ledger.source_publication import verify_source_publications
        with tempfile.TemporaryDirectory(prefix="synthetic-v2-reports-") as temporary:
            root=Path(temporary).resolve();ledger=root/"ledger";ledger.mkdir()
            source=root/"invented.csv";source.write_bytes(fixture(format=VERSION))
            config=root/"parsers.json";config.write_text(json.dumps({"schema_version":1,"enabled":[{"distribution":"wealth-ledger-synthetic-parser","version":"0.1.0","entry_point":"synthetic_v2","adapter_id":"synthetic.holdings-v2"}],"bindings":[]}))
            context=root/"context.json";context.write_text(json.dumps({"schema_version":1,"inputs":[{"evidence_at":"2024-02-01T12:00:00+00:00","source_reference":"synthetic-independent-export","format_selection":VERSION}]}))
            valuation=root/"valuation.json";valuation.write_text(json.dumps({"as_of":"2024-03-01T00:00:00Z","period_start":"2024-01-01T00:00:00Z","generated_at":"2024-03-01T00:00:00Z","report_locale":"en-CA","fx":{"usd_cad":"1.5","usd_twd":"30","usd_cad_date":"2024-02-29","usd_twd_date":"2024-02-29","usd_cad_source":"synthetic-fixed","usd_twd_source":"synthetic-fixed"}}))
            binding=root/"bindings.json";binding.write_text(json.dumps({"schema_version":1,"bindings":[{"provider":"synthetic","source_account_id":"demo-account","target_kind":"new"}]}))
            plan=root/"plan"
            console=Path(sys.executable).parent/("wealth-ledger-source-reports.exe" if sys.platform=="win32" else "wealth-ledger-source-reports")
            from wealth_ledger.workspace import SOURCE_CHECKOUT
            if not SOURCE_CHECKOUT:self.assertTrue(console.is_file())
            command=[str(console)] if console.is_file() else [sys.executable,"-m","wealth_ledger.source_report_cli"]
            def run(*args):
                result=subprocess.run([*command,*map(str,args),"--workspace",str(ledger)],cwd=root,text=True,capture_output=True,timeout=180)
                self.assertEqual(result.returncode,0,result.stdout[-1200:]+result.stderr[-1200:])
                return json.loads(result.stdout)
            review=run("preview",source,"--context",context,"--bindings",binding,"--valuation",valuation,"--config",config,"--plan-directory",plan)
            self.assertEqual(review["observed_totals"]["total_cad"],"125.00")
            self.assertFalse((ledger/"data/db/portfolio.sqlite3").exists())
            source.unlink()
            result=run("confirm","--plan-directory",plan,"--approval-sha256",review["approval_sha256"],"--config",config)
            output=Path(result["output"])
            manifest=verify_bundle(ledger,output,review["operation_id"])
            data=json.loads((output/"data.json").read_text())
            self.assertEqual(data["positions"][0]["source_provider"],"synthetic")
            self.assertIsNone(data["positions"][0]["book_native"])
            self.assertEqual(manifest["source_valuation_id"],1)
            self.assertTrue(all((output/name).is_file() for name in ("portfolio.ods","report.md","report.pdf")))
            before={p.relative_to(output).as_posix():p.read_bytes() for p in output.rglob("*") if p.is_file()}
            import shutil
            shutil.rmtree(plan);config.unlink();context.unlink();valuation.unlink()
            resumed=run("resume","--operation-id",review["operation_id"])
            self.assertEqual(resumed["status"],"already_published")
            self.assertEqual({p.relative_to(output).as_posix():p.read_bytes() for p in output.rglob("*") if p.is_file()},before)
            self.assertEqual(len(read_observations(ledger)),1)
            verify_source_publications(ledger)

    @unittest.skipUnless(WEB, "Optional Web dependencies are not installed")
    def test_independent_v2_web_approval_publication_read_and_exports(self):
        from synthetic_parser.v2 import VERSION
        from wealth_ledger.web.auth import password_hash
        from wealth_ledger.web.config import WebSettings
        from wealth_ledger.web.storage import Store, prepare_instance
        from wealth_ledger.web.jobs import Jobs
        from wealth_ledger.web.worker import execute_isolated
        with tempfile.TemporaryDirectory(prefix="synthetic-v2-web-report-") as temporary:
            root = Path(temporary).resolve()
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
            origin = f"http://localhost:{port}"
            settings = WebSettings(root / "instance", origin); prepare_instance(settings)
            store = Store(settings); supplied = secrets.token_urlsafe(32)
            store.set_owner("owner", password_hash(supplied))
            (settings.data_root / "admin/source-parsers.json").write_text(json.dumps({"schema_version":1,
                "enabled":[{"distribution":"wealth-ledger-synthetic-parser","version":"0.1.0","entry_point":"synthetic_v2","adapter_id":"synthetic.holdings-v2"}],"bindings":[]}))
            client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            def request(path, *, body=None, headers=None, binary=False):
                encoded = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
                base = {"Origin":origin, **({"Content-Type":"application/json"} if body is not None and not isinstance(body, bytes) else {})}
                req = urllib.request.Request(origin + path, data=encoded, headers={**base, **(headers or {})})
                with client.open(req, timeout=60) as response:
                    raw = response.read()
                    return raw if binary else json.loads(raw)
            program = ("import sys; from pathlib import Path; import uvicorn; "
                "from wealth_ledger.web.api import create_app; from wealth_ledger.web.config import WebSettings; "
                "uvicorn.run(create_app(WebSettings(Path(sys.argv[1]),sys.argv[2])),host='127.0.0.1',port=int(sys.argv[3]),log_level='error')")
            process = subprocess.Popen([sys.executable,"-c",program,str(settings.data_root),origin,str(port)],
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    try: request("/healthz"); break
                    except OSError:
                        if process.poll() is not None: self.fail("Synthetic source report API exited")
                        time.sleep(0.1)
                else: self.fail("Synthetic source report API readiness timeout")
                csrf = request("/api/v1/auth/csrf")["csrf_token"]
                session = request("/api/v1/auth/login",body={"username":"owner","password":supplied},headers={"X-CSRF-Token":csrf})
                headers = {"X-CSRF-Token":session["csrf_token"]}
                pid = request("/api/v1/portfolios",body={"name":"Independent synthetic source report"},headers=headers)["id"]
                prefix = "/api/v1/portfolios/" + pid
                upload = request(prefix + "/uploads?kind=source_csv&filename=invented.csv",body=fixture(format=VERSION),headers={**headers,"Content-Type":"text/csv"})
                body = {"upload_ids":[upload["id"]],"contexts":[{"evidence_at":"2024-02-01T12:00:00+00:00","source_reference":"synthetic-independent-web","format_selection":VERSION}],
                    "bindings":[{"provider":"synthetic","source_account_id":"demo-account","target_kind":"new"}],
                    "valuation":{"as_of":"2024-03-01T00:00:00Z","period_start":"2024-01-01T00:00:00Z","generated_at":"2024-03-01T00:00:00Z","report_locale":"en-CA",
                        "fx":{"usd_cad":"1.5","usd_twd":"30","usd_cad_date":"2024-02-29","usd_twd_date":"2024-02-29","usd_cad_source":"synthetic-fixed","usd_twd_source":"synthetic-fixed"}}}
                preview = request(prefix + "/source-report-previews",body=body,headers={**headers,"Idempotency-Key":"independent-web-source-preview"})
                self.assertEqual(execute_isolated(settings,preview["id"]),0)
                saved = Jobs(store).view(Jobs(store).get(pid,preview["id"]))
                self.assertEqual(saved["status"],"ready",saved["error_code"])
                job = request(prefix + "/source-reports",body={"preview_id":saved["id"],"approval_sha256":saved["result"]["approval_sha256"]},headers={**headers,"Idempotency-Key":"independent-web-source-confirm"})
                self.assertEqual(execute_isolated(settings,job["id"]),0)
                published = Jobs(store).view(Jobs(store).get(pid,job["id"]))
                self.assertEqual(published["status"],"published",published["error_code"])
                view = request(prefix + "/reports/" + job["id"])
                self.assertEqual(view["totals"]["total_cad"],"125.00")
                self.assertEqual([row["provider"] for row in view["source_dates"]],["synthetic"])
                self.assertEqual(view["holdings"][0]["source_provider"],"synthetic")
                self.assertIsNone(view["holdings"][0]["book_native"])
                self.assertIsNone(view["source_basis"]["complete_portfolio_returns"])
                exported = request(prefix + "/reports/" + job["id"] + "/export?dataset=holdings&format=json")
                self.assertEqual(exported["rows"],view["holdings"])
                import io, zipfile
                with zipfile.ZipFile(io.BytesIO(request(prefix + "/reports/" + job["id"] + "/bundle.zip",binary=True))) as archive:
                    self.assertTrue({"report.md","report.pdf","portfolio.ods"} <= set(archive.namelist()))
            finally:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=10)
