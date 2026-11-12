"""Opt-in acceptance for the Kurafolio rename upgrade note.

Builds the last pre-rename release from Git history, creates a synthetic instance
with it, follows the README upgrade note's volume copy, and opens the instance
with the current image. Only uniquely named disposable Docker resources are used.
"""
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tarfile
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from docker_context import prepare_context

# Last main commit before the rename (merge of PR 39).
BEFORE_REF = os.environ.get("KURAFOLIO_RENAME_FROM_REF", "324d8b47ae5e10ca04e46ceac33eadc4f0cbe6e4")
ORIGIN = "http://localhost:8000"
HARDENING = ["--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
             "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=256m,uid=10001,gid=10001,mode=0700"]

# Runs inside the web container, so no host port is published.
CLIENT = r"""
import base64, http.cookiejar, json, sys, time, urllib.request, uuid
ORIGIN = 'http://localhost:8000'
args = json.loads(sys.stdin.read())
client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def call(path, body=None, csrf=None, method=None, raw=None, ctype='application/json', idem=False, binary=False):
    headers = {'Origin': ORIGIN}
    if csrf: headers['X-CSRF-Token'] = csrf
    if idem: headers['Idempotency-Key'] = uuid.uuid4().hex
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None: headers['Content-Type'] = ctype
    with client.open(urllib.request.Request(ORIGIN + path, data=data, headers=headers, method=method), timeout=30) as r:
        payload = r.read()
        return payload if binary or r.headers.get_content_type() != 'application/json' else json.loads(payload)
for _ in range(150):
    try: call('/healthz'); break
    except OSError: time.sleep(0.2)
csrf = call('/api/v1/auth/csrf')['csrf_token']
csrf = call('/api/v1/auth/login', {'username': 'owner', 'password': args['supplied']}, csrf)['csrf_token']
if args['mode'] == 'before':
    portfolio = call('/api/v1/portfolios', {'name': 'Synthetic rename portfolio'}, csrf)['id']
    call(f'/api/v1/portfolios/{portfolio}/settings', {'locale': 'zh-TW', 'btc_cost_policy': 'actual_only'}, csrf, 'PUT')
    uploads = [call(f'/api/v1/portfolios/{portfolio}/uploads?kind={kind}&filename=source.csv', raw=base64.b64decode(data),
                    csrf=csrf, ctype='application/octet-stream')['id'] for kind, data in args['files']]
    def completed(job, status):
        for _ in range(240):
            current = call(f'/api/v1/portfolios/{portfolio}/jobs/' + job['id'])
            if current['status'] == status: return current
            assert current['status'] not in {'blocked', 'failed', 'needs_review', 'report_failed'}, current
            time.sleep(0.5)
        raise AssertionError('job did not complete')
    preview = completed(call(f'/api/v1/portfolios/{portfolio}/previews', {'upload_ids': uploads}, csrf, idem=True), 'ready')
    completed(call(f'/api/v1/portfolios/{portfolio}/jobs', {'preview_id': preview['id']}, csrf, idem=True), 'published')
else:
    portfolio = args['portfolio']
import hashlib
state = {'portfolio': portfolio,
         'portfolios': call('/api/v1/portfolios'),
         'settings': call(f'/api/v1/portfolios/{portfolio}/settings'),
         'reports': call(f'/api/v1/portfolios/{portfolio}/reports'),
         'artifacts': call(f'/api/v1/portfolios/{portfolio}/artifacts')['artifacts']}
state['report_views'] = [call(f'/api/v1/portfolios/{portfolio}/reports/' + item['id']) for item in state['reports']['reports']]
# The server re-hashes every artifact against its recorded SHA-256 before serving it.
state['downloads'] = {item['id']: hashlib.sha256(call(f'/api/v1/portfolios/{portfolio}/artifacts/' + item['id'], binary=True)).hexdigest()
                      for item in state['artifacts']}
print(json.dumps(state, sort_keys=True))
"""


def docker(*arguments, **kwargs):
    check = kwargs.pop("check", True)
    kwargs.setdefault("capture_output", True)
    result = subprocess.run(["docker", *arguments], **kwargs)
    if check and result.returncode:
        error = result.stderr if isinstance(result.stderr, str) else (result.stderr or b"").decode(errors="replace")
        raise AssertionError(f"docker {arguments[0]} failed: {error[-2000:]}")
    return result


@unittest.skipUnless(os.environ.get("KURAFOLIO_RENAME_UPGRADE_TEST") == "1",
                     "Rename upgrade acceptance builds two images and is explicitly opt-in")
class RenameUpgradeTests(unittest.TestCase):
    def test_instance_created_before_rename_opens_after_upgrade_note(self):
        docker("info")
        token = "kurafolio-rename-test-" + uuid.uuid4().hex
        old_image, new_image = token + ":before", token + ":after"
        old_volume, new_volume = token + "-before-data", token + "-after-data"
        containers = [token + "-before-web", token + "-before-worker", token + "-after-web"]
        supplied = secrets.token_urlsafe(32)
        files = [[kind, base64.b64encode((ROOT / "examples/data" / name).read_bytes()).decode()]
                 for kind, name in (("csv", "wealthsimple-holdings.csv"), ("fx", "fx.json"))]
        try:
            with tempfile.TemporaryDirectory(prefix="kurafolio-rename-") as temporary:
                base = Path(temporary)
                archive = base / "before.tar"
                subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", "-o", str(archive), BEFORE_REF], check=True)
                with tarfile.open(archive) as bundle:
                    bundle.extractall(base / "before", filter="data")
                subprocess.run([sys.executable, str(base / "before/scripts/docker_context.py"),
                                "--output", str(base / "before-context")], check=True, capture_output=True)
                self.assertTrue((base / "before-context/src/wealth_ledger").is_dir())
                docker("build", "--tag", old_image, str(base / "before-context"), capture_output=False)
                prepare_context(ROOT, base / "after-context")
                docker("build", "--tag", new_image, str(base / "after-context"), capture_output=False)

            # Before: an instance created and used entirely by the pre-rename release.
            docker("volume", "create", old_volume)
            docker("run", "--rm", "-i", *HARDENING, "-v", old_volume + ":/data", old_image,
                   "init-owner", "--password-stdin", input=supplied + "\n", text=True)
            old_env = ["--env", "WEALTH_LEDGER_PUBLIC_ORIGIN=" + ORIGIN]
            docker("run", "--detach", "--name", containers[0], *HARDENING, *old_env, "-v", old_volume + ":/data", old_image)
            docker("run", "--detach", "--name", containers[1], *HARDENING, *old_env, "-v", old_volume + ":/data",
                   old_image, "worker")
            before = json.loads(docker("exec", "-i", containers[0], "python", "-c", CLIENT,
                                       input=json.dumps({"mode": "before", "supplied": supplied, "files": files}),
                                       text=True).stdout)
            self.assertTrue(before["artifacts"])
            docker("rm", "--force", containers[0], containers[1])

            # After: exactly the README note's copy, then the new image with new variables.
            docker("volume", "create", new_volume)
            docker("run", "--rm", "--user", "0", "--network", "none", "--entrypoint", "cp",
                   "-v", old_volume + ":/from:ro", "-v", new_volume + ":/to", new_image, "-a", "/from/.", "/to/")
            docker("run", "--detach", "--name", containers[2], *HARDENING,
                   "--env", "KURAFOLIO_PUBLIC_ORIGIN=" + ORIGIN, "-v", new_volume + ":/data", new_image)
            after = json.loads(docker("exec", "-i", containers[2], "python", "-c", CLIENT,
                                      input=json.dumps({"mode": "after", "supplied": supplied,
                                                        "portfolio": before["portfolio"]}),
                                      text=True).stdout)
            self.assertEqual(after, before)
            self.assertEqual(after["downloads"], {item["id"]: item["sha256"] for item in after["artifacts"]})
        finally:
            # Every name here was generated by this test; no instance resource is touched.
            docker("rm", "--force", *containers, check=False)
            docker("volume", "rm", old_volume, new_volume, check=False)
            docker("image", "rm", old_image, new_image, check=False)


if __name__ == "__main__":
    unittest.main()
