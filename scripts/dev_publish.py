#!/usr/bin/env python3
"""Publish reviewed development changes through an authorized feature branch and PR."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from urllib.parse import urlsplit

from check_publication import AuditError, content_issues, git, scan_history, scan_staged
from check_pr_description import check as check_pr_description


class PublishError(RuntimeError):
    """The saved authorization or local evidence does not permit this operation."""


def command(root: Path, args: list[str], *, env: dict | None = None) -> bytes:
    result = subprocess.run(args, cwd=root, env=env, capture_output=True)
    if result.returncode:
        # Preserve no potentially sensitive command output in exceptions.
        raise PublishError('Command failed: ' + args[0])
    return result.stdout


def remote_identity(url: str) -> tuple[str, str]:
    """Accept credential-free GitHub HTTPS/SSH remotes, never embedded tokens."""
    scp = re.fullmatch(r'git@([A-Za-z0-9.-]+):([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?', url)
    if scp:
        return scp.group(1).lower(), scp.group(2)
    parsed = urlsplit(url)
    if parsed.scheme not in {'https', 'ssh'} or not parsed.hostname or parsed.query or parsed.fragment:
        raise PublishError('Remote URL must be credential-free HTTPS or SSH.')
    if parsed.password or (parsed.username and not (parsed.scheme == 'ssh' and parsed.username == 'git')):
        raise PublishError('Credentials in remote URL are forbidden.')
    if parsed.port is not None:
        raise PublishError('A non-default remote port is not authorized.')
    repository = parsed.path.strip('/')
    if repository.endswith('.git'):
        repository = repository[:-4]
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise PublishError('Malformed repository path.')
    return parsed.hostname.lower(), repository


def load_authorization(root: Path) -> dict:
    path = root / 'config/publish.local.toml'
    if not path.is_file() or path.is_symlink():
        raise PublishError('An ignored config/publish.local.toml authorization is required.')
    tracked = git(root, 'ls-files', '--', 'config/publish.local.toml')
    if tracked.strip():
        raise PublishError('Local authorization must not be tracked.')
    check = subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', '--', 'config/publish.local.toml'])
    if check.returncode != 0:
        raise PublishError('Local authorization must be Git-ignored.')
    try:
        values = tomllib.loads(path.read_text(encoding='utf-8'))['publication']
    except (KeyError, ValueError, OSError) as exc:
        raise PublishError('Invalid publication authorization.') from exc
    required = {'authorized', 'host', 'repository', 'remote', 'feature_prefix', 'create_pr'}
    if not required.issubset(values) or values['authorized'] is not True or values['create_pr'] is not True:
        raise PublishError('Feature-branch and PR publication must be explicitly authorized.')
    if values['host'] != 'github.com':
        raise PublishError('Only github.com is currently supported.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', str(values['repository'])):
        raise PublishError('Malformed authorized repository.')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', str(values['remote'])):
        raise PublishError('Malformed authorized remote.')
    prefix = str(values['feature_prefix'])
    if not prefix.endswith('/') or not re.fullmatch(r'[A-Za-z0-9_/-]+', prefix) or prefix in {'main/', 'master/'}:
        raise PublishError('A safe feature branch prefix is required.')
    return values


def author_is_private_email(email: str) -> bool:
    # GitHub-provided noreply identities avoid disclosing a personal email address.
    return not bool(re.fullmatch(r'(?:[0-9]+\+)?[A-Za-z0-9-]+@users\.noreply\.github\.com', email))


def verify_author(root: Path) -> None:
    identity = git(root, 'var', 'GIT_AUTHOR_IDENT').decode('utf-8').strip()
    match = re.search(r'<([^<>]+)>', identity)
    if not match or author_is_private_email(match.group(1)):
        raise PublishError('Set a GitHub users.noreply.github.com commit email before publication.')
    committer = git(root, 'var', 'GIT_COMMITTER_IDENT').decode('utf-8').strip()
    match = re.search(r'<([^<>]+)>', committer)
    if not match or author_is_private_email(match.group(1)):
        raise PublishError('Committer email must also use GitHub noreply.')


def prepare(root: Path, branch: str | None, body_file: Path | None, message: str | None, title: str | None) -> dict:
    authorization = load_authorization(root)
    remote = authorization['remote']
    urls = git(root, 'remote', 'get-url', '--push', '--all', remote).decode().splitlines()
    if len(urls) != 1 or remote_identity(urls[0]) != (authorization['host'], authorization['repository']):
        raise PublishError('Push remote does not exactly match local authorization.')
    fetch_url = git(root, 'remote', 'get-url', remote).decode().strip()
    if remote_identity(fetch_url) != (authorization['host'], authorization['repository']):
        raise PublishError('Fetch remote does not exactly match local authorization.')
    base_ref = git(root, 'symbolic-ref', 'refs/remotes/' + remote + '/HEAD').decode().strip()
    base = base_ref.removeprefix('refs/remotes/' + remote + '/')
    git(root, 'rev-parse', '--verify', base_ref + '^{commit}')
    current = git(root, 'symbolic-ref', '--short', 'HEAD').decode().strip()
    target = branch or current
    if not target.startswith(authorization['feature_prefix']) or target in {base, 'main', 'master'}:
        raise PublishError('Publication requires an authorized feature branch, never the default branch.')
    command(root, ['git', 'check-ref-format', '--branch', target])
    if target != current:
        # Never switch to an existing branch and risk using unrelated work/history.
        existing = subprocess.run(['git', '-C', str(root), 'show-ref', '--verify', '--quiet', 'refs/heads/' + target])
        if existing.returncode == 0:
            raise PublishError('Switch to the existing feature branch explicitly before publishing.')
        if current != base:
            raise PublishError('Create a new feature branch only from the default branch.')
        if git(root, 'rev-list', base_ref + '..HEAD').strip():
            raise PublishError('Default branch has local commits; move them to a reviewed feature branch first.')
    if git(root, 'diff', '--name-only', '-z'):
        raise PublishError('Unstaged tracked changes exist; review and stage deliberately first.')
    index = scan_staged(root)
    if not index['passed']:
        raise PublishError('Public file/content audit failed; run check_publication.py --staged for details.')
    # Audit all history, including deleted private blobs, before any network action.
    history = scan_history(root, all_history=True)
    if not history['passed']:
        raise PublishError('History audit failed; private content may remain in earlier commits.')
    staged = [item.decode('utf-8', errors='surrogateescape') for item in git(root, 'diff', '--cached', '--name-only', '-z').split(b'\0') if item]
    outgoing = git(root, 'rev-list', base_ref + '..HEAD').decode().splitlines()
    if not staged and not outgoing:
        raise PublishError('No reviewed staged changes or outgoing commits.')
    if staged and not message:
        raise PublishError('A public commit --message is required for staged changes.')
    if not title or not body_file or not body_file.is_file():
        raise PublishError('A reviewed public PR --title and --body-file are required.')
    if not check_pr_description(body_file, root / '.github/pull_request_template.md')['passed']:
        raise PublishError('PR description must follow .github/pull_request_template.md; run check_pr_description.py.')
    public_text = (message or '').encode() + b'\n' + title.encode() + b'\n' + body_file.read_bytes()
    if content_issues(public_text, 'public-description.txt'):
        raise PublishError('Commit or PR description contains a blocked privacy pattern.')
    verify_author(root)
    return {'repository': authorization['repository'], 'host': authorization['host'],
            'head_oid': git(root, 'rev-parse', '--verify', 'HEAD').decode().strip(),
            'index_fingerprint': hashlib.sha256(git(root, 'ls-files', '--stage', '-z')).hexdigest(),
            'description_fingerprint': hashlib.sha256(public_text).hexdigest(),
            'remote': remote, 'base': base, 'base_ref': base_ref, 'current_branch': current,
            'branch': target, 'staged_files': staged, 'outgoing_commits': len(outgoing),
            'create_pr': True, 'execute': False}


def publish(root: Path, plan: dict, *, message: str | None, title: str, body_file: Path) -> dict:
    if not shutil.which('gh'):
        raise PublishError('GitHub CLI is required for development publication only.')
    command(root, ['gh', 'auth', 'status', '--hostname', plan['host']])
    # Resolve the requested repo through the authenticated CLI, before mutation.
    info = json.loads(command(root, ['gh', 'repo', 'view', plan['repository'], '--json', 'nameWithOwner']).decode())
    if info.get('nameWithOwner', '').lower() != plan['repository'].lower():
        raise PublishError('Authenticated repository identity differs from authorization.')
    # Refresh remote metadata; no commits or data are uploaded by fetch.
    command(root, ['git', 'fetch', '--prune', plan['remote']])
    refreshed = prepare(root, plan['branch'], body_file, message, title)
    for key in ('head_oid', 'index_fingerprint', 'description_fingerprint', 'current_branch'):
        if refreshed[key] != plan[key]:
            raise PublishError('Reviewed local inputs changed; obtain a new publication plan.')
    env = dict(os.environ)
    env['PYTHONPATH'] = str(root / 'src')
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    test_python = root / '.venv-portable' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not test_python.is_file():
        test_python = Path(sys.executable)
    command(root, [str(test_python), '-m', 'unittest', 'discover', '-s', 'tests', '-v'], env=env)
    # Re-check after tests; do not auto-stage any files, including test output.
    verified = prepare(root, plan['branch'], body_file, message, title)
    for key in ('head_oid', 'index_fingerprint', 'description_fingerprint', 'current_branch'):
        if verified[key] != refreshed[key]:
            raise PublishError('Tests changed reviewed inputs; review and stage again before publishing.')
    if refreshed['current_branch'] != refreshed['branch']:
        command(root, ['git', 'switch', '-c', refreshed['branch']])
    if refreshed['staged_files']:
        command(root, ['git', 'commit', '-m', str(message)])
    # Build after the final commit so candidate provenance names the exact pushed HEAD.
    image_head = git(root, 'rev-parse', 'HEAD')
    image_index = git(root, 'ls-files', '--stage', '-z')
    command(root, [str(test_python), str(root / 'scripts/check_pr_image.py'), '--root', str(root)])
    if (git(root, 'rev-parse', 'HEAD') != image_head or
            git(root, 'ls-files', '--stage', '-z') != image_index or
            git(root, 'diff', '--name-only', '-z')):
        raise PublishError('Image verification changed reviewed inputs; review before publication.')
    public_text = (message or '').encode() + b'\n' + title.encode() + b'\n' + body_file.read_bytes()
    if hashlib.sha256(public_text).hexdigest() != refreshed['description_fingerprint']:
        raise PublishError('PR text changed during image verification; obtain renewed review.')
    history = scan_history(root, base=refreshed['base_ref'])
    if not history['passed']:
        raise PublishError('Outgoing commit audit failed; nothing has been pushed.')
    command(root, ['git', 'push', '--set-upstream', refreshed['remote'], '--no-follow-tags', 'HEAD:refs/heads/' + refreshed['branch']])
    existing = json.loads(command(root, ['gh', 'pr', 'list', '--repo', refreshed['repository'], '--head', refreshed['branch'], '--base', refreshed['base'], '--state', 'open', '--json', 'url']).decode())
    # Remote lookup must not change the exact reviewed text before create/update.
    latest_text = (message or '').encode() + b'\n' + title.encode() + b'\n' + body_file.read_bytes()
    if hashlib.sha256(latest_text).hexdigest() != refreshed['description_fingerprint']:
        raise PublishError('PR text changed after push; review it before creating or updating the PR.')
    if existing:
        url = existing[0]['url']
        command(root, ['gh', 'pr', 'edit', url, '--repo', refreshed['repository'], '--title', title, '--body-file', str(body_file.resolve())])
    else:
        url = command(root, ['gh', 'pr', 'create', '--repo', refreshed['repository'], '--head', refreshed['branch'], '--base', refreshed['base'], '--title', title, '--body-file', str(body_file.resolve())]).decode().strip()
    return {**refreshed, 'execute': True, 'pull_request_url': url}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--branch')
    parser.add_argument('--message')
    parser.add_argument('--title', required=True)
    parser.add_argument('--body-file', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', help='Run full tests, commit reviewed changes, build/smoke-test the candidate image, then push a feature branch and create/reuse a PR.')
    args = parser.parse_args(argv)
    try:
        plan = prepare(args.root, args.branch, args.body_file, args.message, args.title)
        if args.execute:
            plan = publish(args.root, plan, message=args.message, title=args.title, body_file=args.body_file)
    except (PublishError, AuditError, OSError, ValueError) as exc:
        print('Development publication stopped: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
