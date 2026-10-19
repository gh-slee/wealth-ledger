"""Opt-in Linux container acceptance; creates and removes only unique synthetic resources."""
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from docker_context import prepare_context


def http_client():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def request_json(client, origin, path, body=None, csrf=None, method=None):
    headers = {"Origin": origin}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(origin + path, headers=headers,
        data=json.dumps(body).encode() if body is not None else None, method=method)
    with client.open(request, timeout=5) as response:
        return json.load(response)


def wait_ready(origin, process=None):
    for _ in range(100):
        if process and process.poll() is not None:
            raise AssertionError("Synthetic API process exited before readiness")
        try:
            return request_json(http_client(), origin, "/healthz")
        except (OSError, ValueError):
            time.sleep(0.1)
    raise AssertionError("Synthetic API did not become ready")


def free_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


@unittest.skipUnless(os.environ.get("WEALTH_LEDGER_DOCKER_TEST") == "1", "Docker runtime acceptance is explicitly opt-in")
class DockerRuntimeTests(unittest.TestCase):
    def test_nonroot_readonly_image_and_restart_persistence(self):
        subprocess.run(["docker", "info"], check=True, capture_output=True)
        token = "wealth-ledger-test-" + uuid.uuid4().hex
        volume, container, image = token + "-data", token + "-web", token + ":test"
        volume_created = False
        port = free_port(); origin = f"http://localhost:{port}"
        try:
            with tempfile.TemporaryDirectory(prefix="wealth-ledger-context-") as temporary:
                context = Path(temporary) / "context"
                manifest = prepare_context(ROOT, context)
                self.assertTrue(all(not p.startswith(("data/", "private/", "reports/")) for p in manifest["files"]))
                subprocess.run(["docker", "build", "--tag", image, str(context)], check=True)
            subprocess.run(["docker", "volume", "create", volume], check=True, capture_output=True)
            volume_created = True
            supplied = secrets.token_urlsafe(32)
            subprocess.run(["docker", "run", "--rm", "-i", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,uid=10001,gid=10001,mode=0700",
                "-v", volume + ":/data", image, "init-owner", "--password-stdin"],
                input=supplied+"\n", text=True, check=True, capture_output=True)
            subprocess.run(["docker", "run", "--detach", "--name", container, "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--pids-limit=256", "--memory=1g",
                "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,uid=10001,gid=10001,mode=0700",
                "--publish", f"127.0.0.1:{port}:8000", "--env", "WEALTH_LEDGER_PUBLIC_ORIGIN="+origin,
                "--volume", volume+":/data", image], check=True, capture_output=True)
            wait_ready(origin)
            client = http_client()
            with client.open(origin + "/", timeout=10) as response:
                markup = response.read().decode()
                self.assertIn('id="root"', markup)
                self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
            import re
            script = re.search(r'src="(/assets/[^"]+\.js)"', markup).group(1)
            with client.open(origin + script, timeout=10) as response:
                self.assertGreater(len(response.read()), 1000)
            csrf = request_json(client, origin, "/api/v1/auth/csrf")["csrf_token"]
            csrf = request_json(client, origin, "/api/v1/auth/login", {"username": "owner", "password": supplied}, csrf)["csrf_token"]
            portfolio = request_json(client, origin, "/api/v1/portfolios", {"name": "Synthetic container portfolio"}, csrf)["id"]
            expected = {"locale": "zh-TW", "btc_cost_policy": "bull_average_proxy"}
            request_json(client, origin, f"/api/v1/portfolios/{portfolio}/settings", expected, csrf, "PUT")
            check = "import os,pathlib; assert os.getuid()==10001; assert not pathlib.Path('/app/data').exists(); assert not list(pathlib.Path('/app').rglob('AGENTS.override.md')); assert not list(pathlib.Path('/app').rglob('*.sqlite3')); import shutil; assert shutil.which('node') is None; assert pathlib.Path('/app/frontend/dist/index.html').is_file()"
            subprocess.run(["docker", "exec", container, "python", "-c", check], check=True, capture_output=True)
            platform = subprocess.run(["docker", "exec", container, "python", "-c",
                "import platform,sys; assert sys.platform=='linux'; assert platform.machine() in ('aarch64','x86_64'); print(platform.machine())"],
                check=True, capture_output=True, text=True).stdout.strip()
            expected_platform = os.environ.get("WEALTH_LEDGER_EXPECT_ARCH")
            if expected_platform:
                self.assertEqual(platform, expected_platform)
            print("Synthetic Docker acceptance architecture: " + platform, flush=True)
            subprocess.run(["docker", "stop", container], check=True, capture_output=True)
            # Reconstruct the supported v1 metadata schema offline, preserving owner/settings.
            legacy = "import sqlite3; c=sqlite3.connect('/data/admin/app.sqlite3'); c.executescript('DROP TABLE jobs; DROP TABLE uploads; PRAGMA user_version=1;'); c.close()"
            subprocess.run(["docker", "run", "--rm", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--volume", volume+":/data", "--entrypoint", "python",
                image, "-c", legacy], check=True, capture_output=True)
            subprocess.run(["docker", "run", "--rm", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--volume", volume+":/data", image, "upgrade"],
                check=True, capture_output=True)
            subprocess.run(["docker", "start", container], check=True, capture_output=True)
            wait_ready(origin)
            self.assertEqual(request_json(client, origin, f"/api/v1/portfolios/{portfolio}/settings"), expected)
            subprocess.run(["docker", "kill", "--signal=KILL", container], check=True, capture_output=True)
            subprocess.run(["docker", "start", container], check=True, capture_output=True)
            wait_ready(origin)
            subprocess.run(["docker", "restart", container], check=True, capture_output=True)
            wait_ready(origin)
            self.assertTrue(request_json(client, origin, "/api/v1/auth/session")["authenticated"])
            self.assertEqual(request_json(client, origin, f"/api/v1/portfolios/{portfolio}/settings"), expected)
        finally:
            # These names are generated here, never user-configured instance resources.
            subprocess.run(["docker", "rm", "--force", container], capture_output=True)
            if volume_created:
                subprocess.run(["docker", "volume", "rm", volume], capture_output=True)
            subprocess.run(["docker", "image", "rm", image], capture_output=True)

    def test_compose_health_and_container_replacement_preserve_state(self):
        subprocess.run(["docker", "info"], check=True, capture_output=True)
        token = "wealth-ledger-test-" + uuid.uuid4().hex
        image = token + ":compose"
        port = free_port(); origin = f"http://localhost:{port}"
        with tempfile.TemporaryDirectory(prefix="wealth-ledger-compose-") as temporary:
            base = Path(temporary)
            context = base / "context"
            prepare_context(ROOT, context)
            model = json.loads(subprocess.run(
                ["docker", "compose", "--file", str(ROOT / "compose.yaml"), "config", "--format", "json"],
                check=True, capture_output=True, text=True).stdout)
            # Keep the repository service configuration; isolate only test resources,
            # listener and build context. Never reuse resolved owner volume names.
            model["name"] = token
            model["volumes"] = {"wealth-data": {"name": token + "-data"}}
            model["networks"] = {"default": {}}
            web = model["services"]["web"]
            web["image"] = image
            web["build"]["context"] = str(context)
            web["ports"] = [{"host_ip": "127.0.0.1", "target": 8000,
                             "published": str(port), "protocol": "tcp"}]
            web["environment"]["WEALTH_LEDGER_PUBLIC_ORIGIN"] = origin
            web["restart"] = "no"
            web["healthcheck"].update(interval="1s", start_period="1s")
            model["services"]["worker"]["image"] = image
            model["services"]["worker"]["environment"]["WEALTH_LEDGER_PUBLIC_ORIGIN"] = origin
            model["services"]["worker"]["restart"] = "no"
            config = base / "compose.json"
            config.write_text(json.dumps(model))
            command = ["docker", "compose", "--project-name", token, "--file", str(config)]

            def compose(*arguments, **kwargs):
                return subprocess.run(command + list(arguments), check=True, **kwargs)

            restore_volume = token + "-restored-data"
            restore_container = token + "-restored-web"
            restore_created = False
            try:
                compose("build", "web")
                supplied = secrets.token_urlsafe(32)
                compose("run", "--rm", "--no-deps", "-T", "web", "init-owner", "--password-stdin",
                        input=supplied+"\n", text=True, capture_output=True)
                compose("up", "--detach", "--wait", "--wait-timeout", "30")
                client = http_client()
                csrf = request_json(client, origin, "/api/v1/auth/csrf")["csrf_token"]
                csrf = request_json(client, origin, "/api/v1/auth/login",
                                    {"username": "owner", "password": supplied}, csrf)["csrf_token"]
                portfolio = request_json(client, origin, "/api/v1/portfolios",
                                         {"name": "Synthetic Compose portfolio"}, csrf)["id"]
                expected = {"locale": "en-CA", "btc_cost_policy": "actual_only"}
                self.assertEqual(request_json(client, origin,
                                 f"/api/v1/portfolios/{portfolio}/settings"), expected)
                # End-to-end worker acceptance uses only public invented fixtures.
                uploads = []
                for kind, name in (("csv", "wealthsimple-holdings.csv"), ("fx", "fx.json")):
                    raw = (ROOT / "examples/data" / name).read_bytes()
                    request = urllib.request.Request(origin + f"/api/v1/portfolios/{portfolio}/uploads?kind={kind}&filename=source.csv",
                        data=raw, headers={"Origin": origin, "X-CSRF-Token": csrf,
                                           "Content-Type": "application/octet-stream"})
                    with client.open(request, timeout=10) as response:
                        uploads.append(json.load(response)["id"])

                def submit(path, body):
                    request = urllib.request.Request(origin + path, data=json.dumps(body).encode(),
                        headers={"Origin": origin, "X-CSRF-Token": csrf, "Content-Type": "application/json",
                                 "Idempotency-Key": uuid.uuid4().hex})
                    with client.open(request, timeout=10) as response:
                        return json.load(response)

                def completed(job, status):
                    for _ in range(120):
                        current = request_json(client, origin, f"/api/v1/portfolios/{portfolio}/jobs/" + job["id"])
                        if current["status"] == status:
                            return current
                        self.assertNotIn(current["status"], {"blocked", "failed", "needs_review", "report_failed"}, current)
                        time.sleep(0.5)
                    self.fail("Synthetic container job did not complete")

                preview = completed(submit(f"/api/v1/portfolios/{portfolio}/previews", {"upload_ids": uploads}), "ready")
                formal = completed(submit(f"/api/v1/portfolios/{portfolio}/jobs", {"preview_id": preview["id"]}), "published")
                self.assertTrue(formal["result"]["artifact_ids"])
                # Nonbooking plans use the same image environment in API/child.
                source_request = urllib.request.Request(origin + f"/api/v1/portfolios/{portfolio}/uploads?kind=source_csv&filename=synthetic.csv",
                    data=b"symbol,quantity\nDEMO,1\n", headers={"Origin": origin, "X-CSRF-Token": csrf,
                        "Content-Type": "text/csv"})
                with client.open(source_request, timeout=10) as response:
                    source_upload = json.load(response)["id"]
                source_plan = completed(submit(f"/api/v1/portfolios/{portfolio}/source-plans",
                    {"upload_ids": [source_upload]}), "blocked")
                self.assertEqual(source_plan["error_code"], "no_match")
                self.assertIsNone(source_plan["core_operation_id"])
                reports = request_json(client, origin, f"/api/v1/portfolios/{portfolio}/reports")["reports"]
                self.assertEqual(reports[0]["id"], formal["id"])
                view = request_json(client, origin, f"/api/v1/portfolios/{portfolio}/reports/{formal['id']}")
                self.assertEqual(view["as_of"], formal["result"]["valuation_as_of"])
                self.assertTrue(view["holdings"])
                registered = request_json(client, origin, f"/api/v1/portfolios/{portfolio}/artifacts")["artifacts"]
                self.assertTrue({"application/pdf", "application/vnd.oasis.opendocument.spreadsheet", "text/markdown; charset=utf-8"}
                                .issubset({item["media_type"] for item in registered}))
                before = compose("ps", "--quiet", "web", capture_output=True, text=True).stdout.strip()
                details = json.loads(subprocess.run(["docker", "inspect", before],
                                     check=True, capture_output=True, text=True).stdout)[0]
                self.assertEqual(details["State"]["Health"]["Status"], "healthy")
                self.assertTrue(details["HostConfig"]["ReadonlyRootfs"])
                self.assertEqual(details["Config"]["User"], "10001:10001")
                self.assertTrue(any(mount["Type"] == "volume" and mount["Destination"] == "/data"
                                    for mount in details["Mounts"]))
                self.assertTrue(all((mount["Type"], mount["Destination"]) in
                                    {("volume", "/data"), ("tmpfs", "/tmp")}
                                    for mount in details["Mounts"]))
                compose("up", "--detach", "--force-recreate", "--wait", "--wait-timeout", "30")
                after = compose("ps", "--quiet", "web", capture_output=True, text=True).stdout.strip()
                self.assertNotEqual(before, after)
                self.assertEqual(request_json(client, origin, f"/api/v1/portfolios/{portfolio}/jobs/" + formal["id"])["status"], "published")
                self.assertEqual(request_json(client, origin, f"/api/v1/portfolios/{portfolio}/artifacts")["artifacts"], registered)
                self.assertTrue(request_json(client, origin, "/api/v1/auth/session")["authenticated"])
                self.assertEqual(request_json(client, origin,
                                 f"/api/v1/portfolios/{portfolio}/settings"), expected)
                # Adopt an invented stopped CLI copy using the production host commands.
                # Only this test volume and /tmp are mounted; no personal workspace.
                adoption_script = """
from pathlib import Path
import json, shutil
from wealth_ledger.web.config import WebSettings
from wealth_ledger.web.adoption import prepare_adoption, confirm_adoption
from wealth_ledger.web.backups import database_info
root=Path('/data'); source=root/'portfolios'/PORTFOLIO
legacy=Path('/tmp/stopped-cli'); legacy.mkdir(mode=0o700)
for name in ('data','reports','config','backups'):
    if (source/name).exists(): shutil.copytree(source/name,legacy/name,symlinks=True)
(legacy/'work').mkdir()
# Independently authored legacy manifest around the invented report bytes.
for path in (legacy/'reports').rglob('manifest.json'):
    original=json.loads(path.read_text())
    payload=json.loads((path.parent/'data.json').read_text())
    path.write_text(json.dumps({'snapshot_id':payload['meta']['snapshot_id'],
        'snapshot_as_of':payload['meta']['as_of'],'report_generated_at':original['report_generated_at'],
        'import':original['import'],'workbook_validation':original['workbook_validation'],
        'reporting':original['reporting'],'database_backup':None}))
plan=Path('/tmp/private-cli.adoption.json')
preview=prepare_adoption(WebSettings(root),legacy,'Adopted container CLI',plan,allow_legacy_reports=True)
assert preview['legacy_reports']==1
result=confirm_adoption(WebSettings(root),plan,preview['plan_sha256'])
target=root/'portfolios'/result['portfolio_id']
assert database_info(source/'data/db/portfolio.sqlite3')==database_info(target/'data/db/portfolio.sqlite3')
assert (legacy/'reports/latest.json').read_bytes()==(target/'reports/latest.json').read_bytes()
print(json.dumps(result))
""".replace('PORTFOLIO', repr(portfolio))
                # Full source reports exceed the deployment's 64 MiB /tmp. The
                # invented source exists only for this one-off test container;
                # real deployments use a durable source mount, not /tmp staging.
                original_tmpfs=web["tmpfs"]
                web["tmpfs"]=["/tmp:rw,noexec,nosuid,nodev,size=256m,uid=10001,gid=10001,mode=0700"]
                config.write_text(json.dumps(model))
                try:
                    adoption_result = compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "python",
                        "web", "-c", adoption_script, capture_output=True)
                except subprocess.CalledProcessError as exc:
                    self.fail("Synthetic container adoption failed: " + exc.stderr.decode(errors="replace"))
                finally:
                    web["tmpfs"]=original_tmpfs
                    config.write_text(json.dumps(model))
                adopted = json.loads(adoption_result.stdout)
                self.assertEqual(adopted["status"], "adopted")
                adopted_id=adopted["portfolio_id"]
                editions=request_json(client,origin,f"/api/v1/portfolios/{adopted_id}/reports")["reports"]
                self.assertTrue(editions)
                adopted_report=editions[0]["id"]
                adopted_view=request_json(client,origin,f"/api/v1/portfolios/{adopted_id}/reports/{adopted_report}")
                self.assertEqual(adopted_view["totals"],view["totals"])
                self.assertEqual(adopted_view["report"]["verification_basis"],"migration_capture")
                import io, zipfile
                with client.open(origin+f"/api/v1/portfolios/{adopted_id}/reports/{adopted_report}/bundle.zip") as response:
                    with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                        self.assertIn("migration-verification.json",archive.namelist())
                # Canonical-v2 facts use a separate synthetic portfolio: no report projection yet.
                canonical_id=request_json(client,origin,"/api/v1/portfolios",
                    {"name":"Synthetic canonical-v2 portfolio"},csrf)["id"]
                canonical_seed="""
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal
import hashlib,json
from wealth_ledger import source_v2 as v
from wealth_ledger.source_protocol import AccountKey,AdapterInfo,Money,RecordKey
from wealth_ledger.source_ingestion import SourceInput,new_binding,prepare_ingestion,commit_ingestion,read_facts,require_report_projection,IngestionError
from wealth_ledger.workspace import resolve_workspace
project=Path('/data/portfolios')/PORTFOLIO
raw=b'format,id,amount\\nsynthetic-v2,funding-001,100\\n'
at=datetime(2024,1,31,12,tzinfo=timezone.utc)
a=AccountKey('synthetic','canonical-001')
info=AdapterInfo('synthetic','synthetic.v2','0.1.0',('synthetic-v2',),('cash_flows',),api_version=2)
context=v.ParseContext(at,'synthetic-docker-fixture',format_selection='synthetic-v2')
evidence=v.Evidence(hashlib.sha256(raw).hexdigest(),context,at,'Explicit source event ID')
flow=v.CashFlow(RecordKey(a,'funding-001','r1'),at,'deposit','in',Money(Decimal('100.00'),'CAD'),'completed','unclassified')
batch=v.NormalizedBatch(info,'synthetic-v2',evidence,(v.Account(a,'crypto','Synthetic canonical account','crypto'),),
    v.Membership('exported-accounts','s1',(a,),'partial','Explicit synthetic scope'),(),
    (v.Coverage('cash_flows',a,at,at,'partial','Explicit synthetic scope','events','s1'),),(flow,))
plan=prepare_ingestion(project,(SourceInput(batch,raw),),bindings=(new_binding(a),))
result=commit_ingestion(resolve_workspace(explicit=project),plan)
assert result['new_records']==1 and not result['report_projection_ready']
try:require_report_projection(project)
except IngestionError as exc:assert exc.code=='report_projection_unavailable'
else:raise AssertionError('Unprojected facts must block new reports')
print(hashlib.sha256(json.dumps(read_facts(project),sort_keys=True).encode()).hexdigest())
""".replace('PORTFOLIO',repr(canonical_id))
                canonical_result=compose("run","--rm","--no-deps","-T","--entrypoint","python","web","-c",canonical_seed,capture_output=True)
                canonical_hash=canonical_result.stdout.decode().strip()
                self.assertEqual(len(canonical_hash),64)
                # Full private archive roundtrip to a different empty volume; source stays intact.
                bundle_request = urllib.request.Request(origin + f"/api/v1/portfolios/{portfolio}/reports/{formal['id']}/bundle.zip")
                with client.open(bundle_request, timeout=15) as response:
                    self.assertTrue(response.read(2).startswith(b"PK"))
                archive = compose("run", "--rm", "--no-deps", "-T", "web", "backup", "--stdout", capture_output=True).stdout
                self.assertTrue(archive.startswith(b"PK"))
                subprocess.run(["docker", "volume", "create", restore_volume],check=True,capture_output=True)
                restore_created = True
                isolated = ["docker","run","--rm","--read-only","--cap-drop=ALL","--security-opt=no-new-privileges",
                            "--tmpfs","/tmp:rw,noexec,nosuid,nodev,uid=10001,gid=10001,mode=0700",
                            "--volume",restore_volume+":/data"]
                restored = subprocess.run([*isolated,"-i",image,"restore","--stdin"],input=archive,check=True,capture_output=True)
                self.assertEqual(json.loads(restored.stdout)["status"],"restored")
                subprocess.run([*isolated,image,"worker","--once"],check=True,capture_output=True)
                canonical_check=("import hashlib,json; from pathlib import Path; "
                    "from wealth_ledger.source_ingestion import read_facts; "
                    "print(hashlib.sha256(json.dumps(read_facts(Path('/data/portfolios')/"+repr(canonical_id)+"),sort_keys=True).encode()).hexdigest())")
                recovered=subprocess.run([*isolated,"--entrypoint","python",image,"-c",canonical_check],check=True,capture_output=True,text=True)
                self.assertEqual(recovered.stdout.strip(),canonical_hash)
                new_port=free_port();new_origin=f"http://localhost:{new_port}"
                subprocess.run(["docker","run","--detach","--name",restore_container,"--read-only","--cap-drop=ALL",
                    "--security-opt=no-new-privileges","--pids-limit=256","--memory=1g",
                    "--tmpfs","/tmp:rw,noexec,nosuid,nodev,uid=10001,gid=10001,mode=0700",
                    "--volume",restore_volume+":/data","--publish",f"127.0.0.1:{new_port}:8000",
                    "--env","WEALTH_LEDGER_PUBLIC_ORIGIN="+new_origin,image],check=True,capture_output=True)
                wait_ready(new_origin)
                try:
                    request_json(client,new_origin,"/api/v1/auth/session")
                    self.fail("Restored sessions must be revoked")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code,401)
                restored_client=http_client()
                restored_csrf=request_json(restored_client,new_origin,"/api/v1/auth/csrf")["csrf_token"]
                request_json(restored_client,new_origin,"/api/v1/auth/login",{"username":"owner","password":supplied},restored_csrf)
                restored_view=request_json(restored_client,new_origin,f"/api/v1/portfolios/{portfolio}/reports/{formal['id']}")
                self.assertEqual(restored_view["totals"],view["totals"])
                self.assertEqual(restored_view["holdings"],view["holdings"])
                restored_adopted=request_json(restored_client,new_origin,f"/api/v1/portfolios/{adopted_id}/reports/{adopted_report}")
                self.assertEqual(restored_adopted["totals"],adopted_view["totals"])
                self.assertEqual(restored_adopted["report"]["verification_basis"],"migration_capture")
                with restored_client.open(new_origin+f"/api/v1/portfolios/{adopted_id}/reports/{adopted_report}/bundle.zip") as response:
                    self.assertEqual(response.read(2),b"PK")
                self.assertEqual(request_json(restored_client,new_origin,f"/api/v1/portfolios/{portfolio}/artifacts")["artifacts"],registered)
                self.assertEqual(request_json(client,origin,f"/api/v1/portfolios/{portfolio}/settings"),expected)
            finally:
                subprocess.run(["docker","rm","--force",restore_container],capture_output=True)
                if restore_created:
                    subprocess.run(["docker","volume","rm",restore_volume],capture_output=True)
                subprocess.run(command + ["down", "--volumes", "--remove-orphans"], capture_output=True)
                subprocess.run(["docker", "image", "rm", image], capture_output=True)


if __name__ == "__main__":
    unittest.main()
