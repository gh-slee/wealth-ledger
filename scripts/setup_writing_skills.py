#!/usr/bin/env python3
"""Fetch missing repository writing skills as text; preserve every existing copy."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import stat
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 256 * 1024
SOURCES = {
    'caveman': {'repository': 'JuliusBrussee/caveman',
                'files': {'SKILL.md': 'skills/caveman/SKILL.md', 'LICENSE': 'LICENSE',
                          'NOTICE': 'NOTICE', 'LICENSE-MIT': 'LICENSE-MIT'}},
    'humanizer': {'repository': 'blader/humanizer',
                  'files': {'SKILL.md': 'SKILL.md', 'LICENSE': 'LICENSE'}},
}


class SetupError(RuntimeError):
    """Setup is incomplete; existing instructions must remain untouched."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SetupError('Unexpected upstream redirect; no redirected request was sent')


def fetch(url: str) -> bytes:
    """Use public HTTPS only, without credentials or shell installers."""
    try:
        import certifi
    except ImportError:
        context = ssl.create_default_context()
    else:
        context = ssl.create_default_context(cafile=certifi.where())
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(url, headers={
        'User-Agent': 'wealth-ledger-writing-setup', 'Accept': 'application/json, text/plain'})
    with opener.open(request, timeout=15) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise SetupError('Upstream text exceeds the size limit')
    return data


def text(data: bytes) -> str:
    if not isinstance(data, bytes) or len(data) > MAX_BYTES or b'\0' in data:
        raise SetupError('Expected bounded upstream text')
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        raise SetupError('Upstream text is not UTF-8') from None


def validate_skill(data: bytes, name: str) -> None:
    value = text(data)
    front = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)', value, re.S)
    if not front or not re.search(r'^name: *' + re.escape(name) + r' *$', front[1], re.M):
        raise SetupError('Upstream skill has missing or unexpected metadata')
    if not re.search(r'^description: *\S', front[1], re.M):
        raise SetupError('Upstream skill has no discovery description')


def safe_directory(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(mode):
        raise SetupError('Refusing a symlink or non-directory in the skill path')
    return True


def skill_parent(root: Path, *, create: bool) -> Path:
    root = root.resolve(strict=True)
    # Inspect every component before reading or creating through it.
    for ancestor in (*reversed(root.parents), root):
        if not safe_directory(ancestor):
            raise SetupError('Repository root does not exist')
    parent = root
    for part in ('.agents', 'skills'):
        parent = parent / part
        if not safe_directory(parent):
            if create:
                try:
                    parent.mkdir()
                except FileExistsError:
                    safe_directory(parent)
            else:
                return parent
    return parent


def existing(parent: Path, name: str) -> dict | None:
    target = parent / name
    if not safe_directory(target):
        return None
    skill = target / 'SKILL.md'
    try:
        mode = skill.lstat().st_mode
    except FileNotFoundError:
        raise SetupError('Existing skill directory is incomplete; preserve it and inspect manually') from None
    if not stat.S_ISREG(mode):
        raise SetupError('Existing skill must be a regular file')
    if skill.stat().st_size > MAX_BYTES:
        raise SetupError('Existing skill exceeds the size limit')
    data = skill.read_bytes()
    validate_skill(data, name)
    return {'name': name, 'status': 'present', 'path': '.agents/skills/' + name,
            'sha256': hashlib.sha256(data).hexdigest(), 'network_used': False}


def install(parent: Path, name: str, get=fetch) -> dict:
    source = SOURCES[name]
    metadata = json.loads(text(get('https://api.github.com/repos/' +
                                   source['repository'] + '/commits/HEAD')))
    commit = metadata.get('sha') if isinstance(metadata, dict) else None
    if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise SetupError('Upstream did not supply an exact commit')
    with tempfile.TemporaryDirectory(prefix='.writing-download-', dir=parent) as directory:
        staged = Path(directory) / name
        staged.mkdir()
        hashes = {}
        for filename, upstream in source['files'].items():
            data = get('https://raw.githubusercontent.com/' + source['repository'] +
                       '/' + commit + '/' + upstream)
            text(data)
            if filename == 'SKILL.md':
                validate_skill(data, name)
            (staged / filename).write_bytes(data)
            hashes[filename] = hashlib.sha256(data).hexdigest()
        receipt = {'schema_version': 1, 'repository': source['repository'],
                   'commit': commit, 'fetched_at': datetime.now(timezone.utc).isoformat(),
                   'files_sha256': hashes, 'policy': 'latest_when_missing; never overwrite existing skills'}
        (staged / '_origin.json').write_text(json.dumps(receipt, indent=2) + '\n')
        # A complete concurrent installation wins; never replace its nonempty directory.
        current = existing(parent, name)
        if current is not None:
            return current
        try:
            os.rename(staged, parent / name)
        except OSError:
            current = existing(parent, name)
            if current is None:
                raise
            return current
    return {'name': name, 'status': 'installed', 'path': '.agents/skills/' + name,
            'commit': commit, 'sha256': hashes['SKILL.md'], 'network_used': True}


def setup(root: Path, *, ensure: bool, get=fetch) -> dict:
    parent = skill_parent(root, create=ensure)
    rows = []
    for name in SOURCES:
        current = existing(parent, name) if parent.exists() else None
        rows.append(current or (install(parent, name, get) if ensure else
                                {'name': name, 'status': 'missing', 'network_used': False}))
    return {'ready': all(row['status'] != 'missing' for row in rows), 'skills': rows,
            'policy': 'Fetch upstream HEAD only when absent; preserve existing copies',
            'scope': 'Optional development instructions; no application runtime changes'}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--ensure', action='store_true', help='Download only missing skills from upstream HEAD')
    mode.add_argument('--check', action='store_true', help='Check repository copies without network or writes')
    args = parser.parse_args(argv)
    try:
        result = setup(ROOT, ensure=args.ensure)
    except (OSError, ValueError, SetupError) as error:
        # Exception details can include upstream response bodies or local paths.
        print(json.dumps({'ready': False, 'error': type(error).__name__,
                          'detail': str(error) if isinstance(error, SetupError) else 'Upstream transport or metadata could not be verified',
                          'action': 'Check network access, HTTPS trust and local skill paths; existing copies are retained'}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
