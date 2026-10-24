#!/usr/bin/env python3
"""Build and smoke-test a local PR candidate without accessing an existing instance."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

from docker_context import prepare_context

ROOT = Path(__file__).resolve().parents[1]
SMOKE = r'''
import json, os, pathlib, platform, re, secrets, subprocess, time, urllib.error, urllib.request
from wealth_ledger.web.auth import password_hash
from wealth_ledger.web.config import WebSettings
from wealth_ledger.web.storage import prepare_instance, Store
assert os.getuid() == 10001
assert not pathlib.Path('/app/data').exists()
assert not list(pathlib.Path('/app').rglob('AGENTS.override.md'))
assert not list(pathlib.Path('/app').rglob('*.sqlite3'))
assert not list(pathlib.Path('/app').rglob('.impeccable'))
settings = WebSettings.from_environment()
prepare_instance(settings)
Store(settings).set_owner('synthetic', password_hash(secrets.token_urlsafe(32)))
subprocess.run(['python', '/app/scripts/web.py', 'worker', '--once'], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
process = subprocess.Popen(['python', '/app/scripts/web.py', 'serve', '--host', '127.0.0.1'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
origin = 'http://localhost:8000'
try:
    for attempt in range(300):
        if process.poll() is not None:
            raise RuntimeError('Candidate API exited before readiness')
        try:
            with client.open(origin + '/healthz', timeout=2) as response:
                assert response.status == 200
            break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError('Candidate API did not become ready')
    with client.open(origin + '/', timeout=5) as response:
        markup = response.read().decode()
        assert 'id="root"' in markup
        assert "script-src 'self'" in response.headers['Content-Security-Policy']
    script = re.search(r'src="(/assets/[^"\s]+\.js)"', markup).group(1)
    with client.open(origin + script, timeout=5) as response:
        assert len(response.read()) > 1000
    try:
        client.open(origin + '/api/v1/portfolios', timeout=5)
        raise AssertionError('Anonymous financial API unexpectedly accessible')
    except urllib.error.HTTPError as error:
        assert error.code == 401
    print(json.dumps({'health': True, 'browser_assets': True, 'anonymous_api_401': True,
                      'worker_once': True, 'architecture': platform.machine()}))
finally:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
'''


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def committed_head(root: Path) -> str:
    if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
        raise ValueError('Choose the repository root')
    if git(root, 'status', '--porcelain=v1', '--untracked-files=no'):
        raise ValueError('Commit reviewed changes first; image checks require a clean tracked tree')
    return git(root, 'rev-parse', '--verify', 'HEAD')


def run(args: list[str], output: Path, *, source: str | None = None, timeout=1800) -> str:
    # Output remains in ignored local evidence; never include build output in a PR.
    with output.open('w', encoding='utf-8') as log:
        result = subprocess.run(args, input=source, text=True, stdout=log,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Candidate check failed; inspect local ' + output.name)
    return output.read_text(encoding='utf-8')


def check(root: Path) -> dict:
    root = root.resolve()
    head = committed_head(root)
    work = root / 'work'
    if work.is_symlink() or (work / 'pr-images').is_symlink():
        raise ValueError('Image evidence directories must not be symlinks')
    token = uuid.uuid4().hex
    evidence = work / 'pr-images' / token
    evidence.mkdir(parents=True, mode=0o700)
    subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', '--', str(evidence)], check=True)
    manifest = prepare_context(root, evidence / 'context')
    tracked = set(subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z'], text=True).split('\0'))
    if set(manifest['files']) - tracked:
        raise ValueError('Image inputs include uncommitted files; review and commit them first')
    context_sha = hashlib.sha256(json.dumps(manifest['files'], sort_keys=True).encode()).hexdigest()
    image = 'wealth-ledger:pr-' + head[:12] + '-' + token[:12]
    run(['docker', 'info'], evidence / 'daemon.log', timeout=30)
    run(['docker', 'build', '--tag', image, '--label', 'org.opencontainers.image.revision=' + head,
         '--label', 'io.wealth-ledger.context-sha256=' + context_sha, str(evidence / 'context')],
        evidence / 'build.log')
    metadata = json.loads(run(['docker', 'image', 'inspect', image], evidence / 'image.json', timeout=30))[0]
    image_id = metadata['Id']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
        raise ValueError('Image identity is missing')
    if metadata['Config']['User'] != '10001:10001':
        raise ValueError('Candidate must use the nonroot application user')
    labels = metadata['Config']['Labels']
    if labels['org.opencontainers.image.revision'] != head or labels['io.wealth-ledger.context-sha256'] != context_sha:
        raise ValueError('Image provenance does not match committed inputs')
    container = 'wealth-ledger-pr-check-' + token
    try:
        smoke = json.loads(run(['docker', 'run', '--rm', '--interactive', '--name', container,
            '--network', 'none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
            '--pids-limit=128', '--memory=1g',
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,uid=10001,gid=10001,mode=0700',
            '--tmpfs', '/data:rw,nosuid,nodev,uid=10001,gid=10001,mode=0700',
            '--entrypoint', 'python', image_id, '-'], evidence / 'smoke.log', source=SMOKE, timeout=120))
    finally:
        # This unpredictable name belongs only to this invocation, never a real service.
        subprocess.run(['docker', 'rm', '--force', container], capture_output=True, timeout=30)
    if not all(smoke.get(k) is True for k in ('health', 'browser_assets', 'anonymous_api_401', 'worker_once')):
        raise ValueError('Candidate smoke evidence is incomplete')
    if committed_head(root) != head:
        raise ValueError('Source changed during build; commit and rerun the image check')
    current = prepare_context(root, evidence / 'verified-context')
    if current['files'] != manifest['files']:
        raise ValueError('Image inputs changed during verification')
    receipt = {'schema_version': 1, 'status': 'passed', 'head': head, 'image': image,
               'image_id': image_id, 'context_sha256': context_sha, 'smoke': smoke,
               'checked_at': datetime.now(timezone.utc).isoformat(),
               'receipt': str(evidence.relative_to(root) / 'receipt.json'),
               'scope': 'Local candidate only; ephemeral synthetic data, no host mounts or published ports'}
    (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        result = check(args.root)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('PR image verification stopped: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
