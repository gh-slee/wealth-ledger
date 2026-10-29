#!/usr/bin/env python3
"""Fail-closed, local-only audit of files and Git history proposed for publication."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import stat
import subprocess
import sys
import zipfile
import io

PUBLIC_ROOT_FILES = {
    '.gitignore', '.gitattributes', 'AGENTS.md', 'README.md', 'TODO.md', 'PRODUCT.md', 'DESIGN.md',
    'LICENSE', 'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md', 'THIRD_PARTY_NOTICES.md',
    'pyproject.toml', 'build_backend.py', 'MANIFEST.in', 'requirements-build.lock', 'requirements.txt', 'requirements.lock', '.env.example',
    'requirements-web.txt', 'requirements-web.lock', 'requirements-web-test.lock',
    'requirements-pg.lock', 'requirements-pg-test.lock', 'compose.pg-foundation.yaml',
    'Dockerfile', '.dockerignore', 'compose.yaml',
}
PUBLIC_DOCS = {
    'core-api.md', 'user-manual.md', 'workbook.md', 'report-spec.md', 'ui-design-workflow.md',
    'ux-p0-001-first-run.md', 'ux-p0-002-status.md', 'ux-p0-002-status-design.md', 'ux-p0-003-imports.md',
    'ux-p1-001-activity.md', 'ux-p1-002-performance.md', 'ux-p1-003-income.md',
    'ux-p1-004-allocation.md', 'ux-p1-005-analysis.md', 'ux-p1-006-sources.md',
    'ux-p1-007-distribution.md', 'ux-p2-001-risk.md', 'ux-p2-002-goals.md',
    'ux-p2-003-mobile.md', 'ux-p2-004-operations.md', 'ux-p2-005-tax-evidence.md',
    'getting-started.md', 'product-ux-review.md', 'spec-development.md', 'capability-status.md',
    'canonical-domain.md', 'postgres-foundation.md', 'web-v2-identity.md', 'web-v2-sources.md',
    'btc-reconciliation-plan.md', 'publishing.md', 'development.md',
    'source-adapters.md', 'source-ingestion.md', 'source-projections.md', 'parser-sdk.md', 'i18n-plan.md', 'self-hosted-webapp.md', 'agent-development.md', 'web-operations.md', 'web-imports.md', 'web-frontend.md', 'web-analysis-reports.md', 'web-backups.md', 'web-financial-records.md', 'web-adoption.md', 'web-release-acceptance.md', 'web-legacy-reports.md',
}
PUBLIC_CONFIG = {
    'company-aliases.json', 'project.example.toml', 'crypto-opening.example.json',
    'bull-opening.example.json', 'source-catalog.example.json', 'fx.example.json', 'publish.example.toml', 'local.example.toml',
}
PUBLIC_FUND_FIXTURES = {
    'README.md', 'blackrock.csv', 'bmo.json', 'ci.html', 'fidelity.json',
    'invesco.json', 'vanguard.json', 'vaneck.xlsx',
}
PUBLIC_README_PNGS = {
    'assets/readme/report-preview.png', 'assets/readme/web-overview.png',
    'assets/readme/web-getting-started.png',
    'assets/readme/web-exposure.png', 'assets/readme/web-login.png',
    'assets/readme/web-holdings.png', 'assets/readme/web-history.png',
    'assets/readme/web-bitcoin.png', 'assets/readme/web-imports.png',
    'assets/readme/web-records.png', 'assets/readme/web-reports.png',
    'assets/readme/web-settings.png', 'assets/readme/web-overview-dark.png',
    'assets/readme/web-report-reader.png',
}
PUBLIC_ROLE_SKILLS = frozenset({
    '.agents/skills/wealthledger-fintech-pm/SKILL.md',
    '.agents/skills/wealthledger-software-architect/SKILL.md',
    '.agents/skills/wealthledger-fullstack-developer/SKILL.md',
    '.agents/skills/wealthledger-qa-automation/SKILL.md',
})
PRIVATE_INSTRUCTION_NAMES = {'agents.override.md'}
IGNORED_ROOTS = {
    '.git', 'data', 'reports', 'backups', 'work', 'private', 'outputs', 'output',
    'dist', 'build', 'node_modules', 'venv', 'htmlcov', '.cursor', '.codex', '.agents',
    '.pytest_cache', '.mypy_cache', '.ruff_cache', '.impeccable',
}
PRIVATE_SUFFIXES = ('.db', '.sqlite', '.sqlite3', '.pem', '.key', '.p12', '.pfx',
                    '.keystore', '.log', '.bak', '.pyc', '.pyo', '.zip', '.zip.part')
SECRET_PATTERNS = (
    ('private key', re.compile(rb'-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----')),
    ('GitHub credential', re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b')),
    ('AWS access key', re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b')),
    ('credential-bearing URL', re.compile(rb'https?://[^\s/:]+:[^\s/@]+@')),
    ('private adoption plan', re.compile(rb'"format"\s*:\s*"wealth-ledger-private-' + rb'adoption"')),
    ('explicit private fixture marker', re.compile(rb'\b(?:PRIVATE_' + rb'FINANCIAL_FIXTURE|DO_NOT_PUBLISH_' + rb'PERSONAL_DATA)\b')),
    ('machine-specific home path', re.compile(rb'/(?:Users|home)/[A-Za-z0-9_.-]+/')),
)
ASSIGNMENT = re.compile(
    rb'''(?im)^[ \t]*(?:["']?)(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret[_-]?key|client[_-]?secret)(?:["']?)[ \t]*[:=][ \t]*["']?([^\r\n"'#]{8,})'''
)
PLACEHOLDERS = ('example', 'placeholder', 'changeme', 'your_', 'your-', '<', 'os.',
                'getenv', 'environ', 'none', 'false', 'null')
MAX_TEXT_BYTES = 8 * 1024 * 1024


class AuditError(RuntimeError):
    """Local evidence is insufficient to authorize publication."""


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True)
    if result.returncode:
        # Git errors may contain URLs; report only the operation, never stderr.
        raise AuditError('Git operation failed: ' + args[0])
    return result.stdout


def path_allowed(path: str) -> bool:
    p = PurePosixPath(path)
    if p.is_absolute() or '..' in p.parts or '\\' in path or not p.parts or p.as_posix() != path or any(ord(ch) < 32 or 0xD800 <= ord(ch) <= 0xDFFF for ch in path):
        return False
    parts = p.parts
    if p.name.casefold() in PRIVATE_INSTRUCTION_NAMES:
        return False
    if any(part in {'__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.impeccable'} for part in parts):
        return False
    if any(part.startswith('.venv') for part in parts):
        return False
    # Exact reviewed repository skills are the only exception to the private root.
    # Keep this after malformed/private-name validation, before ignored-root denial.
    if path in PUBLIC_ROLE_SKILLS:
        return True
    if parts[0] in IGNORED_ROOTS or path.lower().endswith(PRIVATE_SUFFIXES):
        return False
    if len(parts) == 1:
        return path in PUBLIC_ROOT_FILES
    if parts[0] == 'frontend':
        if any(part in {'node_modules', 'dist', 'test-results', 'playwright-report'} or part.startswith('.') for part in parts[1:]):
            return False
        if len(parts) == 2:
            return p.name in {'package.json', 'package-lock.json', 'tsconfig.json', 'vite.config.ts',
                              'vitest.config.ts', 'playwright.config.ts', 'index.html', 'components.json'}
        if parts[1] in {'src', 'tests'}:
            return p.suffix in {'.ts', '.tsx', '.css'} or (len(parts) == 4 and parts[1:3] == ('src', 'locales')
                and p.name in {'en-CA.json', 'zh-TW.json', 'zh-CN.json'})
        if parts[1] == 'scripts':
            return len(parts) == 3 and p.name in {'check-source.mjs', 'capture-readme.mjs'}
        return len(parts) == 4 and parts[1:3] == ('public', 'licenses') and p.name in {
            'ibm-plex-sans-condensed.txt', 'atkinson-hyperlegible.txt', 'shadcn-ui.txt'}
    if parts[0] == 'src':
        return (len(parts) >= 3 and parts[1] == 'wealth_ledger' and p.suffix == '.py'
                or len(parts) == 4 and parts[1:3] == ('wealth_ledger', 'locales')
                and p.name in {'registry.json', 'legacy.json', 'en-CA.json', 'zh-TW.json', 'zh-CN.json'})
    if parts[0] == 'scripts':
        return len(parts) == 2 and p.suffix == '.py'
    if parts[0] == 'tests':
        if len(parts) == 2:
            return p.name.startswith('test_') and p.suffix == '.py'
        return len(parts) == 4 and (parts[1:3] == ('fixtures', 'fund_sources') and p.name in PUBLIC_FUND_FIXTURES
                or parts[1:3] == ('fixtures', 'postgres_foundation') and p.name in {'golden.json','oracles.json'}
                or parts[1:3] == ('fixtures', 'identity_v2') and p.name == 'oracle.json'
                or parts[1:3] == ('fixtures', 'source_capabilities') and p.name in {'catalog.json','oracle.json','Dockerfile','worker.py','fake_api.py','README.md'})
    if parts[0] == 'examples':
        if path in {'examples/parser-plugin/pyproject.toml', 'examples/parser-plugin/README.md', 'examples/parser-plugin/LICENSE',
                    'examples/parser-plugin/src/synthetic_parser/__init__.py', 'examples/parser-plugin/src/synthetic_parser/v2.py',
                    'examples/parser-plugin/tests/test_synthetic_parser.py', 'examples/parser-plugin/tests/test_installed_api.py'}:
            return True
        if len(parts) == 2:
            return p.name in {'README.md', 'demo.py'}
        if len(parts) == 3 and parts[1] == 'data':
            return p.name in {'wealthsimple-holdings.csv', 'bull-orders.csv', 'fx.json', 'btc-price.json'}
        return len(parts) == 3 and parts[1] == 'templates' and p.name in {'btc_events.csv', 'cash_flows.csv'}
    if parts[0] == 'docs':
        return len(parts) == 2 and p.name in PUBLIC_DOCS
    if parts[0] == 'config':
        return len(parts) == 2 and p.name in PUBLIC_CONFIG
    if parts[:2] == ('assets', 'readme'):
        return len(parts) == 3 and (p.name in {'wealth-ledger-mark.svg', 'README.md'} or path in PUBLIC_README_PNGS)
    if parts[:2] == ('assets', 'fonts'):
        return len(parts) == 3 and p.name in {'NotoSansTC-Regular.ttf', 'NotoSansSC-Regular.ttf', 'NotoSansSC-provenance.json', 'OFL.txt', 'OFL-SC.txt', 'README.md'}
    if parts[0] == '.githooks':
        return len(parts) == 2 and p.name in {'pre-commit', 'pre-push'}
    if path == '.github/pull_request_template.md':
        return True
    if parts[:2] == ('.github', 'workflows'):
        return len(parts) == 3 and p.name in {'ci.yml', 'ci.yaml'}
    return False


def content_issues(data: bytes, path: str) -> list[str]:
    is_readme_preview = path in PUBLIC_README_PNGS
    if is_readme_preview:
        # These named images come from synthetic fixtures and need visual review.
        if (len(data) < 45 or len(data) > 4 * 1024 * 1024
                or data[:8] != b'\x89PNG\r\n\x1a\n' or data[8:16] != b'\x00\x00\x00\x0dIHDR'
                or data[-12:] != b'\x00\x00\x00\x00IEND\xaeB`\x82'):
            return ['invalid or oversized README preview PNG']
        width, height = struct.unpack('>II', data[16:24])
        if not (1 <= width <= 4000 and 1 <= height <= 4000):
            return ['README preview dimensions exceed the reviewed limit']
    if path.endswith('.ttf'):
        # Vendored font license/provenance is reviewed separately in the manifest.
        return [] if data[:4] in {b'\x00\x01\x00\x00', b'OTTO', b'ttcf'} else ['invalid font container']
    if path.endswith('.xlsx'):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                info = archive.infolist()
                if sum(item.file_size for item in info) > MAX_TEXT_BYTES:
                    return ['oversized spreadsheet fixture']
                data = b'\n'.join(archive.read(item) for item in info if item.filename.endswith('.xml'))
        except (zipfile.BadZipFile, OSError):
            return ['invalid spreadsheet fixture']
    if len(data) > MAX_TEXT_BYTES:
        return ['oversized text file']
    if b'\x00' in data and not is_readme_preview:
        return ['unexpected binary file']
    issues = [reason for reason, pattern in SECRET_PATTERNS if pattern.search(data)]
    safe_typed_fields = set()
    if path.endswith('.py'):
        try:
            tree = ast.parse(data.decode('utf-8'))
            for node in ast.walk(tree):
                if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                        and node.target.id == 'password' and isinstance(node.annotation, ast.Name)
                        and node.annotation.id == 'SecretStr' and isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Name) and node.value.func.id == 'Field'
                        and not node.value.args and len(node.value.keywords) == 2
                        and {k.arg for k in node.value.keywords} == {'min_length', 'max_length'}
                        and all(isinstance(k.value, ast.Constant) and type(k.value.value) is int
                                and 0 < k.value.value <= 1024 for k in node.value.keywords)):
                    safe_typed_fields.add(node.lineno)
        except (UnicodeError, SyntaxError):
            pass
    for match in ASSIGNMENT.finditer(data):
        # Exact inert type declarations and catalog labels are not credentials.
        # Other values in these files still pass all secret/assignment checks.
        if path == 'frontend/src/lib/schema.d.ts' and re.fullmatch(rb'\s*password: string;', match.group(0)):
            continue
        if path == 'frontend/src/locales/en-CA.json' and match.group(0).strip() == b'"password": "Password':
            continue
        line_number = data[:match.start()].count(b"\n") + 1
        # This exact live form read, like getpass below, contains no credential.
        if path == 'frontend/src/App.tsx' and re.fullmatch(
                rb'\s*password: values\.get\("password"\),', data.splitlines()[line_number-1]):
            continue
        if line_number in safe_typed_fields:
            continue
        if re.fullmatch(rb"""[ \t]*[\"']?password[\"']?[ \t]*[:=][ \t]*getpass\.getpass\(""", match.group(0)):
            continue
        value = match.group(1).decode('utf-8', errors='replace').strip().lower()
        if not any(word in value for word in PLACEHOLDERS):
            issues.append('possible credential assignment')
            break
    return issues


def new_result(mode: str) -> dict:
    return {'mode': mode, 'passed': False, 'files': [], 'violations': [],
            'limitations': ['Pattern checks cannot prove absence of personal data; review the public manifest.']}


def record(result: dict, path: str, data: bytes | None, *, origin: str, mode: str = '100644') -> None:
    errors = []
    if not path_allowed(path):
        errors.append('path is outside the public allowlist')
    if mode not in {'100644', '100755'}:
        errors.append('symlink, submodule, or unsupported Git mode')
    if data is not None:
        errors.extend(content_issues(data, path))
    if errors:
        result['violations'].append({'path': path, 'origin': origin, 'reasons': errors})
    else:
        result['files'].append({'path': path, 'origin': origin,
                                'sha256': hashlib.sha256(data).hexdigest() if data is not None else None,
                                'bytes': len(data) if data is not None else 0})


def finish(result: dict) -> dict:
    result['passed'] = not result['violations']
    return result


def public_role_candidate(root: Path, relative: str) -> tuple[Path | None, str | None]:
    """Inspect each path component before any target read, including dangling links."""
    if relative not in PUBLIC_ROLE_SKILLS:
        raise ValueError('Not a reviewed role skill path')
    parts = PurePosixPath(relative).parts
    candidate = root
    for index, part in enumerate(parts):
        candidate = candidate / part
        try:
            mode = candidate.lstat().st_mode
        except FileNotFoundError:
            return None, None
        if stat.S_ISLNK(mode):
            return None, 'public role skill or ancestor is a symlink'
        # Case-insensitive filesystems can resolve a differently spelled private
        # path to this candidate. Require actual directory-entry spelling too.
        if part not in {entry.name for entry in candidate.parent.iterdir()}:
            return None, 'public role skill or ancestor spelling differs from allowlist'
        if index < len(parts) - 1:
            if not stat.S_ISDIR(mode):
                return None, 'public role skill ancestor is not a directory'
        elif not stat.S_ISREG(mode):
            return None, 'public role skill is not a regular file'
    return candidate, None


def scan_worktree(root: Path) -> dict:
    """Build a source-only manifest; unknown non-private files fail closed."""
    result = new_result('worktree')
    # rglob deliberately omits the private .agents root below. Inspect only the
    # four reviewed candidates explicitly, never following a file/ancestor link.
    for relative in sorted(PUBLIC_ROLE_SKILLS):
        candidate, problem = public_role_candidate(root, relative)
        if problem:
            result['violations'].append({'path': relative, 'origin': 'worktree',
                                         'reasons': [problem]})
        elif candidate is not None:
            record(result, relative, candidate.read_bytes(), origin='worktree')
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root).as_posix()
        parts = PurePosixPath(rel).parts
        # Private guidance is intentionally absent from source-only manifests.
        # The index/history scanners still reject it, even after force-add.
        if path.name.casefold() in PRIVATE_INSTRUCTION_NAMES:
            continue
        if parts[:3] == ('examples', 'parser-plugin', 'build'):
            continue  # Generated example build output; index/history still reject it.
        if parts[0] != 'examples' and not path_allowed(rel) and path.suffix.lower() in {'.csv', '.ods', '.pdf', '.xlsx'}:
            continue
        if path.name in {'.DS_Store', 'Thumbs.db', '.coverage'} or rel.lower().endswith(PRIVATE_SUFFIXES):
            continue
        if parts[0] in IGNORED_ROOTS or any(part in {'.git', '__pycache__', 'node_modules', 'dist', 'test-results', 'playwright-report', '.impeccable'} or part.startswith('.venv') or part.endswith('.egg-info') for part in parts):
            continue
        if len(parts) >= 2 and parts[0] == 'config' and parts[1] not in PUBLIC_CONFIG:
            continue  # Ignored private config; Git modes still reject if tracked.
        if parts[0].startswith('.env') and rel != '.env.example':
            continue
        if rel == 'docs/session-handoff.md':
            continue
        if path.is_symlink():
            record(result, rel, None, origin='worktree', mode='120000')
        elif path.is_file():
            record(result, rel, path.read_bytes(), origin='worktree')
    return finish(result)


def tree_entries(root: Path, revision: str) -> list[tuple[str, str, str]]:
    out = git(root, 'ls-tree', '-r', '-z', revision)
    entries = []
    for row in out.split(b'\0'):
        if not row:
            continue
        meta, raw_path = row.split(b'\t', 1)
        mode, kind, oid = meta.decode('ascii').split()
        entries.append((mode, oid, raw_path.decode('utf-8', errors='surrogateescape')))
    return entries


def scan_staged(root: Path) -> dict:
    # Audit the whole index, including tracked private files unchanged this commit.
    result = new_result('staged')
    for row in git(root, 'ls-files', '--stage', '-z').split(b'\0'):
        if not row:
            continue
        meta, raw_path = row.split(b'\t', 1)
        mode, oid, stage = meta.decode('ascii').split()
        path = raw_path.decode('utf-8', errors='surrogateescape')
        if stage != '0':
            result['violations'].append({'path': path, 'origin': 'index', 'reasons': ['unresolved merge']})
            continue
        data = git(root, 'cat-file', 'blob', oid) if mode in {'100644', '100755', '120000'} else None
        record(result, path, data, origin='index', mode=mode)
    return finish(result)


def scan_history(root: Path, *, base: str | None = None, head: str = 'HEAD', all_history: bool = False) -> dict:
    result = new_result('outgoing-history')
    if not all_history and not base:
        raise AuditError('An explicit base ref or --all-history is required.')
    head_oid = git(root, 'rev-parse', '--verify', head + '^{commit}').decode().strip()
    revisions = [head_oid]
    if base and not all_history:
        base_oid = git(root, 'rev-parse', '--verify', base + '^{commit}').decode().strip()
        revisions.append('^' + base_oid)
    commits = git(root, 'rev-list', *revisions).decode().splitlines()
    seen: set[tuple[str, str, str]] = set()
    for commit in commits:
        for mode, oid, path in tree_entries(root, commit):
            key = (mode, oid, path)
            if key in seen:
                continue
            seen.add(key)
            data = git(root, 'cat-file', 'blob', oid) if mode in {'100644', '100755', '120000'} else None
            record(result, path, data, origin=commit, mode=mode)
        emails = git(root, 'show', '-s', '--format=%ae%n%ce', commit).decode().splitlines()
        # GitHub web merges use its public system noreply as committer.
        # Authors and locally created commits still require users.noreply identities.
        user_noreply = r'(?:[0-9]+\+)?[A-Za-z0-9-]+@users\.noreply\.github\.com'
        if (len(emails) != 2 or not re.fullmatch(user_noreply, emails[0])
                or not (emails[1] == 'noreply@github.com' or re.fullmatch(user_noreply, emails[1]))):
            result['violations'].append({'path': '(commit identity)', 'origin': commit, 'reasons': ['commit email is not a GitHub noreply identity']})
        message = git(root, 'show', '-s', '--format=%B', commit)
        for reason in content_issues(message, 'commit-message.txt'):
            result['violations'].append({'path': '(commit message)', 'origin': commit, 'reasons': [reason]})
    result['commits_checked'] = len(commits)
    return finish(result)


def scan_pre_push(root: Path, lines: str) -> dict:
    result = new_result('pre-push')
    for line in lines.splitlines():
        fields = line.split()
        if len(fields) != 4:
            raise AuditError('Malformed pre-push input.')
        local_ref, local_oid, remote_ref, remote_oid = fields
        if set(local_oid) == {'0'}:
            raise AuditError('Automatic branch deletion is not permitted.')
        # Scan all reachable history, even when a private blob was later deleted.
        child = scan_history(root, head=local_oid, all_history=True)
        result['files'].extend(child['files'])
        result['violations'].extend(child['violations'])
    return finish(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--worktree', action='store_true')
    mode.add_argument('--staged', action='store_true')
    mode.add_argument('--outgoing', metavar='BASE_REF')
    mode.add_argument('--all-history', action='store_true')
    mode.add_argument('--pre-push', action='store_true')
    parser.add_argument('--manifest', type=Path, help='Optional audit JSON output (use an ignored private/work directory).')
    args = parser.parse_args(argv)
    try:
        if args.worktree:
            result = scan_worktree(args.root)
        elif args.staged:
            result = scan_staged(args.root)
        elif args.pre_push:
            result = scan_pre_push(args.root, sys.stdin.read())
        else:
            result = scan_history(args.root, base=args.outgoing, all_history=args.all_history)
    except (AuditError, OSError) as exc:
        print('Publication audit could not complete: ' + str(exc), file=sys.stderr)
        return 2
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(output + '\n', encoding='utf-8')
    print(output)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
