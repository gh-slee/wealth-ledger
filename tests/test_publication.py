"""Publication guard tests use isolated synthetic Git repositories only."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import check_publication as guard
import dev_publish as publisher


class PublicationPolicyTests(unittest.TestCase):
    def test_curated_public_paths(self):
        for path in ('build_backend.py', 'MANIFEST.in', 'requirements-build.lock', 'docs/parser-sdk.md',
                     'examples/parser-plugin/pyproject.toml', 'examples/parser-plugin/LICENSE',
                     'examples/parser-plugin/tests/test_installed_api.py',
                     'README.md', 'PRODUCT.md', 'DESIGN.md', 'docs/ux-p0-002-status-design.md', 'src/wealth_ledger/core.py', 'scripts/update.py',
                     'tests/test_publication.py', 'config/publish.example.toml',
                     'docs/development.md', '.githooks/pre-push', 'examples/data/wealthsimple-holdings.csv',
                     'examples/data/bull-orders.csv', 'examples/data/fx.json',
                     'examples/data/btc-price.json', 'examples/templates/btc_events.csv',
                     'examples/templates/cash_flows.csv', 'THIRD_PARTY_NOTICES.md',
                     '.github/pull_request_template.md', 'config/local.example.toml',
                     'docs/i18n-plan.md', 'docs/self-hosted-webapp.md', 'docs/agent-development.md', 'docs/web-imports.md', 'src/wealth_ledger/locales/en-CA.json',
                     'src/wealth_ledger/locales/zh-CN.json', 'src/wealth_ledger/locales/legacy.json',
                     'assets/fonts/NotoSansSC-Regular.ttf', 'assets/fonts/OFL-SC.txt',
                     'assets/fonts/NotoSansSC-provenance.json',
                     'assets/readme/wealth-ledger-mark.svg', 'assets/readme/report-preview.png',
                     'assets/readme/README.md', 'frontend/package-lock.json', 'frontend/src/App.tsx',
                     'frontend/src/locales/zh-TW.json', 'docs/web-frontend.md',
                     'frontend/scripts/capture-readme.mjs', 'assets/readme/web-overview.png',
                     'assets/readme/web-exposure.png', 'assets/readme/web-login.png',
                     'assets/readme/web-holdings.png', 'assets/readme/web-history.png',
                     'assets/readme/web-bitcoin.png', 'assets/readme/web-imports.png',
                     'assets/readme/web-records.png', 'assets/readme/web-reports.png',
                     'assets/readme/web-settings.png', 'assets/readme/web-overview-dark.png',
                     'assets/readme/web-report-reader.png', 'assets/readme/web-getting-started.png',
                     'docs/ux-p0-001-first-run.md', 'docs/ux-p0-002-status.md', 'docs/ux-p0-003-imports.md',
                     'docs/ux-p1-001-activity.md', 'docs/ux-p1-002-performance.md', 'docs/ux-p1-003-income.md',
                     'docs/ux-p1-004-allocation.md', 'docs/ux-p1-005-analysis.md', 'docs/ux-p1-006-sources.md',
                     'docs/ux-p1-007-distribution.md', 'docs/ux-p2-001-risk.md', 'docs/ux-p2-002-goals.md',
                     'docs/ux-p2-003-mobile.md', 'docs/ux-p2-004-operations.md', 'docs/ux-p2-005-tax-evidence.md',
                     'docs/getting-started.md', 'docs/product-ux-review.md', 'docs/ui-design-workflow.md'):
            self.assertTrue(guard.path_allowed(path), path)

    def test_private_and_unknown_paths(self):
        for path in ('data/raw/export.csv', 'reports/report.md', 'backups/history.db',
                     'config/publish.local.toml', 'docs/session-handoff.md', 'private/readme.md',
                     'src/wealth_ledger/__pycache__/core.py', 'scripts/token.key',
                     'tests/fixtures/user.csv', 'examples/data/user-holdings.csv',
                     'examples/templates/private.csv', 'examples/arbitrary/example.csv',
                     'examples/parser-plugin/build/lib/synthetic_parser/__init__.py',
                     'examples/parser-plugin/private.csv', 'examples/parser-plugin/.env',
                     'examples/parser-plugin/AGENTS.override.md', 'src/wealth_ledger/_bundle/private.json',
                     'examples/demo.csv', 'PRODUCT.local.md', 'DESIGN.local.md', 'unreviewed.md', '../README.md', '/README.md',
                     'src\\wealth_ledger\\core.py', '.github/workflows/deploy.yml',
                     'src/wealth_ledger/locales/user.json', 'assets/fonts/downloaded-font.ttf',
                     'assets/readme/private-screenshot.png', 'assets/readme/export.csv',
                     'docs/private-webapp-notes.md', 'AGENTS.override.md',
                     'docs/AGENTS.override.md', 'src/wealth_ledger/AGENTS.override.md',
                     'src/wealth_ledger/locales/AGENTS.override.md',
                     'scripts/AGENTS.OVERRIDE.MD', 'frontend/AGENTS.override.md',
                     'frontend/src/AGENTS.override.md', 'frontend/.env', 'frontend/dist/index.html',
                     'frontend/node_modules/private.json', 'frontend/src/user.json', 'frontend/public/wallet.csv',
                     'assets/readme/wallet.png', 'frontend/scripts/arbitrary-capture.mjs',
                     'instance-backup.zip', 'instance-backup.zip.part', 'docs/backup.zip'):
            self.assertFalse(guard.path_allowed(path), path)

    def test_synthetic_secret_patterns(self):
        secrets = (b'ghp_' + b'a' * 36, b'AKIA' + b'A' * 16,
                   b'-----BEGIN ' + b'PRIVATE KEY-----',
                   b'PRIVATE_' + b'FINANCIAL_FIXTURE',
                   b'https://' + b'example:credential@example.invalid',
                   b'password' + b' = "very-private-value"',
                   b'/Users/' + b'example/private.csv')
        for data in secrets:
            self.assertTrue(guard.content_issues(data, 'README.md'), repr(data[:8]))

    def test_frontend_inert_fields_do_not_allow_secret_values(self):
        self.assertEqual(guard.content_issues(b'  password: string;', 'frontend/src/lib/schema.d.ts'), [])
        self.assertEqual(guard.content_issues(b'  "password": "Password"', 'frontend/src/locales/en-CA.json'), [])
        self.assertEqual(guard.content_issues(b' password: values.get("password"),', 'frontend/src/App.tsx'), [])
        for path in ('frontend/src/App.tsx', 'frontend/src/lib/schema.d.ts', 'frontend/src/locales/en-CA.json'):
            self.assertTrue(guard.content_issues(b'password = "never-use-this-synthetic-value"', path))

    def test_placeholder_is_allowed(self):
        self.assertEqual(guard.content_issues(b'password = "YOUR_PASSWORD"', 'README.md'), [])

    def test_unknown_binary_and_invalid_font(self):
        self.assertTrue(guard.content_issues(b'abc\0abc', 'README.md'))
        self.assertTrue(guard.content_issues(b'not a font', 'assets/fonts/NotoSansTC-Regular.ttf'))

    def test_only_named_reviewed_readme_pngs_have_bounded_binary_support(self):
        import base64
        import struct
        import zlib
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
        for path in sorted(guard.PUBLIC_README_PNGS):
            with self.subTest(path=path):
                self.assertEqual(guard.content_issues(png, path), [])
                self.assertTrue(guard.content_issues(b'not an image', path))
                self.assertTrue(guard.content_issues(png[:-12], path))
                self.assertTrue(guard.content_issues(png[:16]+struct.pack('>II',4001,1)+png[24:], path))
                text = b'Comment\x00ghp_' + b'a'*36 + b' '
                chunk = struct.pack('>I',len(text)) + b'tEXt' + text + struct.pack('>I',zlib.crc32(b'tEXt'+text))
                self.assertTrue(guard.content_issues(png[:-12] + chunk + png[-12:], path))
        self.assertTrue(guard.content_issues(png, 'assets/readme/private.png'))

    def test_scanner_and_tests_do_not_match_their_own_patterns(self):
        for path in (SCRIPTS / 'check_publication.py', Path(__file__)):
            self.assertEqual(guard.content_issues(path.read_bytes(), path.name), [])

    def test_remote_forms(self):
        for url in ('https://github.com/example/project.git',
                    'git@github.com:example/project.git',
                    'ssh://git@github.com/example/project.git'):
            self.assertEqual(publisher.remote_identity(url), ('github.com', 'example/project'))

    def test_remote_credential_or_ambiguity_rejected(self):
        for url in ('https://token@github.com/example/project',
                    'https://' + 'example:credential@github.com/example/project',
                    'https://github.com/example/project?token=value',
                    'https://github.com/example/project/extra',
                    'ssh://git@github.com:2222/example/project',
                    '/tmp/project.git', 'https://github.com/example/project#ref'):
            with self.assertRaises((publisher.PublishError, ValueError)):
                publisher.remote_identity(url)

    def test_public_commit_email_policy(self):
        self.assertFalse(publisher.author_is_private_email('example@users.noreply.github.com'))
        self.assertFalse(publisher.author_is_private_email('123+example@users.noreply.github.com'))
        self.assertTrue(publisher.author_is_private_email('example@example.invalid'))


@unittest.skipUnless(__import__('shutil').which('git'), 'Git is needed for isolated repository tests')
class PublicationGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run_git('init', '-b', 'main')
        self.run_git('config', 'user.name', 'Example Maintainer')
        self.run_git('config', 'user.email', 'example@users.noreply.github.com')
        self.write('README.md', '# Example project\n')
        self.run_git('add', '--', 'README.md')
        self.run_git('commit', '-m', 'Initial public code')

    def tearDown(self):
        self.temp.cleanup()

    def run_git(self, *args):
        result = subprocess.run(['git', '-C', str(self.root), *args], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        return result.stdout.decode().strip()

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding='utf-8')
        return target

    def authorize(self):
        self.write('.gitignore', '/config/*.local.toml\n/private/\n')
        self.run_git('add', '.gitignore')
        self.run_git('commit', '-m', 'Ignore local settings')
        self.write('config/publish.local.toml', '''[publication]
authorized = true
host = "github.com"
repository = "example/project"
remote = "origin"
feature_prefix = "feature/"
create_pr = true
''')
        self.run_git('remote', 'add', 'origin', 'https://github.com/example/project.git')
        self.run_git('update-ref', 'refs/remotes/origin/main', self.run_git('rev-parse', 'HEAD'))
        self.run_git('symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
        return self.write('private/pr.txt', 'Public change and validation.\n')

    def test_clean_index_and_all_history_pass(self):
        self.assertTrue(guard.scan_staged(self.root)['passed'])
        self.assertTrue(guard.scan_history(self.root, all_history=True)['passed'])

    def test_history_accepts_public_github_system_committer_only(self):
        with mock.patch.dict(os.environ, {'GIT_COMMITTER_EMAIL': 'noreply@github.com'}):
            self.run_git('commit', '--allow-empty', '-m', 'Synthetic web merge')
            self.assertTrue(guard.scan_history(self.root, all_history=True)['passed'])
            with self.assertRaises(publisher.PublishError):
                publisher.verify_author(self.root)

    def test_github_committer_does_not_allow_private_author(self):
        with mock.patch.dict(os.environ, {'GIT_AUTHOR_EMAIL': 'private@example.invalid',
                                          'GIT_COMMITTER_EMAIL': 'noreply@github.com'}):
            self.run_git('commit', '--allow-empty', '-m', 'Synthetic identity fixture')
        self.assertFalse(guard.scan_history(self.root, all_history=True)['passed'])

    def test_history_rejects_private_or_lookalike_system_committer(self):
        for address in ('private@example.invalid', 'noreply@github.com.example.invalid'):
            with self.subTest(address=address):
                with mock.patch.dict(os.environ, {'GIT_COMMITTER_EMAIL': address}):
                    self.run_git('commit', '--allow-empty', '-m', 'Synthetic identity fixture')
                result = guard.scan_history(self.root, all_history=True)
                self.assertFalse(result['passed'])
                latest = self.run_git('rev-parse', 'HEAD')
                self.assertTrue(any(row['origin'] == latest and row['path'] == '(commit identity)'
                                    for row in result['violations']))

    def test_private_overrides_are_ignored_and_omitted_from_worktree_manifest(self):
        self.write('.gitignore', (SCRIPTS.parent / '.gitignore').read_text())
        paths = ('AGENTS.override.md', 'src/wealth_ledger/AGENTS.override.md')
        for path in paths:
            self.write(path, 'Private synthetic owner guidance.\n')
            self.run_git('check-ignore', '-q', '--', path)
            self.assertEqual(self.run_git('ls-files', '--', path), '')
        result = guard.scan_worktree(self.root)
        self.assertTrue(result['passed'])
        self.assertFalse(set(paths) & {entry['path'] for entry in result['files']})

    def test_force_added_private_override_blocks_the_whole_index(self):
        self.write('.gitignore', 'AGENTS.override.md\n')
        self.write('AGENTS.override.md', 'Private synthetic owner guidance.\n')
        self.run_git('add', '-f', '--', 'AGENTS.override.md')
        result = guard.scan_staged(self.root)
        self.assertFalse(result['passed'])
        self.assertTrue(any(entry['path'] == 'AGENTS.override.md'
                            for entry in result['violations']))
        self.run_git('commit', '-m', 'Synthetic private instruction fixture')
        self.write('README.md', '# Other reviewed change\n')
        self.run_git('add', '--', 'README.md')
        self.assertFalse(guard.scan_staged(self.root)['passed'])

    def test_deleted_nested_override_still_blocks_history_and_pre_push(self):
        base = self.run_git('rev-parse', 'HEAD')
        path = 'src/wealth_ledger/AGENTS.override.md'
        self.write('.gitignore', 'AGENTS.override.md\n')
        self.write(path, 'Private synthetic owner guidance.\n')
        self.run_git('add', '-f', '--', path)
        self.run_git('commit', '-m', 'Synthetic nested instruction fixture')
        self.run_git('rm', '--', path)
        self.run_git('commit', '-m', 'Remove synthetic private fixture')
        self.assertTrue(guard.scan_staged(self.root)['passed'])
        for result in (guard.scan_history(self.root, all_history=True),
                       guard.scan_history(self.root, base=base),
                       guard.scan_pre_push(self.root,
                           'refs/heads/main ' + self.run_git('rev-parse', 'HEAD')
                           + ' refs/heads/feature/test ' + '0' * 40 + '\n')):
            self.assertFalse(result['passed'])
            self.assertTrue(any(entry['path'] == path for entry in result['violations']))

    def test_design_state_is_ignored_and_excluded_from_worktree(self):
        self.write('.gitignore', (SCRIPTS.parent / '.gitignore').read_text())
        paths = ('.impeccable/critique/synthetic.json',
                 'src/wealth_ledger/.impeccable/capture.py')
        for path in paths:
            self.write(path, 'Private synthetic design state.\n')
            self.run_git('check-ignore', '-q', '--', path)
            self.assertFalse(guard.path_allowed(path))
        result = guard.scan_worktree(self.root)
        self.assertTrue(result['passed'])
        self.assertFalse(set(paths) & {row['path'] for row in result['files']})

    def test_force_added_design_state_blocks_index_and_history(self):
        self.write('.gitignore', '.impeccable/\n')
        path = 'src/wealth_ledger/.impeccable/capture.py'
        self.write(path, '# Private synthetic design state\n')
        self.run_git('add', '-f', '--', path)
        self.assertFalse(guard.scan_staged(self.root)['passed'])
        self.run_git('commit', '-m', 'Synthetic forced design-state fixture')
        self.assertFalse(guard.scan_history(self.root, all_history=True)['passed'])

    def test_staged_secret_is_found(self):
        self.write('README.md', 'Example credential: ' + 'ghp_' + 'a' * 36)
        self.run_git('add', 'README.md')
        result = guard.scan_staged(self.root)
        self.assertFalse(result['passed'])
        self.assertNotIn('a' * 36, str(result))

    def test_tracked_private_file_is_found_even_when_unchanged(self):
        self.write('data/raw/holdings.csv', 'synthetic,private\n')
        self.run_git('add', 'data/raw/holdings.csv')
        self.run_git('commit', '-m', 'Synthetic private fixture')
        self.write('README.md', '# Reviewed public change\n')
        self.run_git('add', 'README.md')
        self.assertFalse(guard.scan_staged(self.root)['passed'])

    def test_deleted_private_file_in_history_still_blocks(self):
        base = self.run_git('rev-parse', 'HEAD')
        self.write('private/history.csv', 'synthetic,private\n')
        self.run_git('add', 'private/history.csv')
        self.run_git('commit', '-m', 'Synthetic private fixture')
        self.run_git('rm', 'private/history.csv')
        self.run_git('commit', '-m', 'Remove fixture')
        self.assertTrue(guard.scan_staged(self.root)['passed'])
        result = guard.scan_history(self.root, base=base)
        self.assertFalse(result['passed'])
        self.assertTrue(any(item['path'] == 'private/history.csv' for item in result['violations']))

    def test_deleted_secret_in_old_blob_still_blocks(self):
        self.write('README.md', 'ghp_' + 'a' * 36)
        self.run_git('add', 'README.md')
        self.run_git('commit', '-m', 'Synthetic credential fixture')
        self.write('README.md', '# Clean now\n')
        self.run_git('add', 'README.md')
        self.run_git('commit', '-m', 'Remove synthetic credential')
        self.assertFalse(guard.scan_history(self.root, all_history=True)['passed'])

    def test_rename_and_newline_path_are_not_hidden(self):
        self.run_git('mv', 'README.md', 'private\nfile.md')
        result = guard.scan_staged(self.root)
        self.assertFalse(result['passed'])
        self.assertEqual(result['violations'][0]['path'], 'private\nfile.md')

    @unittest.skipIf(os.name == 'nt', 'Symlinks require local permission on Windows')
    def test_symlink_is_rejected(self):
        (self.root / 'examples').mkdir()
        (self.root / 'examples/link.csv').symlink_to('../README.md')
        self.run_git('add', 'examples/link.csv')
        self.assertFalse(guard.scan_staged(self.root)['passed'])

    def test_missing_history_base_fails_closed(self):
        with self.assertRaises(guard.AuditError):
            guard.scan_history(self.root)
        with self.assertRaises(guard.AuditError):
            guard.scan_history(self.root, base='not-a-ref')

    def test_pre_push_inspects_reachable_history(self):
        oid = self.run_git('rev-parse', 'HEAD')
        line = f'refs/heads/feature/example {oid} refs/heads/feature/example {"0" * 40}\n'
        self.assertTrue(guard.scan_pre_push(self.root, line)['passed'])
        with self.assertRaises(guard.AuditError):
            guard.scan_pre_push(self.root, 'malformed\n')

    def test_worktree_skips_known_private_but_rejects_unknown_public(self):
        self.write('private/notes.md', 'Do not publish\n')
        self.write('data/db/history.sqlite3', 'private\n')
        self.write('config/publish.local.toml', 'private config\n')
        self.assertTrue(guard.scan_worktree(self.root)['passed'])
        self.write('unknown.md', 'Review me first\n')
        self.assertFalse(guard.scan_worktree(self.root)['passed'])

    def test_publish_missing_authorization_rejected(self):
        with self.assertRaises(publisher.PublishError):
            publisher.prepare(self.root, 'feature/test', None, None, 'Title')

    def test_publish_dry_plan_does_not_commit_or_stage(self):
        body = self.authorize()
        self.write('README.md', '# Reviewed change\n')
        self.run_git('add', 'README.md')
        before = self.run_git('rev-parse', 'HEAD')
        plan = publisher.prepare(self.root, 'feature/test', body, 'Public improvement', 'Public improvement')
        self.assertEqual(plan['staged_files'], ['README.md'])
        self.assertFalse(plan['execute'])
        self.assertEqual(before, self.run_git('rev-parse', 'HEAD'))
        self.assertEqual(self.run_git('branch', '--show-current'), 'main')

    def test_publish_main_or_wrong_remote_rejected(self):
        body = self.authorize()
        self.write('README.md', '# Reviewed change\n')
        self.run_git('add', 'README.md')
        with self.assertRaises(publisher.PublishError):
            publisher.prepare(self.root, 'main', body, 'Message', 'Title')
        self.run_git('remote', 'set-url', 'origin', 'https://github.com/different/project.git')
        with self.assertRaises(publisher.PublishError):
            publisher.prepare(self.root, 'feature/test', body, 'Message', 'Title')

    def test_publish_unstaged_changes_or_missing_remote_head_rejected(self):
        body = self.authorize()
        self.write('README.md', '# Unstaged change\n')
        with self.assertRaises(publisher.PublishError):
            publisher.prepare(self.root, 'feature/test', body, 'Message', 'Title')
        self.run_git('add', 'README.md')
        self.run_git('symbolic-ref', '--delete', 'refs/remotes/origin/HEAD')
        with self.assertRaises(guard.AuditError):
            publisher.prepare(self.root, 'feature/test', body, 'Message', 'Title')

    def test_publish_author_identity_rejected(self):
        body = self.authorize()
        self.write('README.md', '# Reviewed change\n')
        self.run_git('add', 'README.md')
        self.run_git('config', 'user.email', 'example@example.invalid')
        with self.assertRaises(publisher.PublishError):
            publisher.prepare(self.root, 'feature/test', body, 'Message', 'Title')

    def test_no_automatic_staging_of_untracked_source(self):
        body = self.authorize()
        self.write('README.md', '# Reviewed change\n')
        self.run_git('add', 'README.md')
        self.write('scripts/unrelated.py', 'print("unrelated")\n')
        plan = publisher.prepare(self.root, 'feature/test', body, 'Message', 'Title')
        self.assertEqual(plan['staged_files'], ['README.md'])
        self.assertEqual(self.run_git('ls-files', 'scripts/unrelated.py'), '')


    def test_tracked_authorization_is_rejected(self):
        self.authorize()
        self.run_git('add', '-f', 'config/publish.local.toml')
        with self.assertRaises(publisher.PublishError):
            publisher.load_authorization(self.root)

    def test_authorization_must_explicitly_enable_pr_workflow(self):
        self.authorize()
        path = self.root / 'config/publish.local.toml'
        path.write_text(path.read_text().replace('authorized = true', 'authorized = false'))
        with self.assertRaises(publisher.PublishError):
            publisher.load_authorization(self.root)

    def test_new_feature_branch_cannot_reuse_existing_branch_silently(self):
        body = self.authorize()
        self.run_git('branch', 'feature/existing')
        self.write('README.md', '# Reviewed change\n')
        self.run_git('add', 'README.md')
        with self.assertRaises(publisher.PublishError):
            publisher.prepare(self.root, 'feature/existing', body, 'Message', 'Title')

    def test_private_committed_email_blocks_history(self):
        self.run_git('config', 'user.email', 'example@example.invalid')
        self.write('README.md', '# Reviewed change\n')
        self.run_git('add', 'README.md')
        self.run_git('commit', '-m', 'Public change with unsuitable identity')
        self.assertFalse(guard.scan_history(self.root, all_history=True)['passed'])

    def test_pre_push_deletion_is_rejected(self):
        with self.assertRaises(guard.AuditError):
            guard.scan_pre_push(self.root, f'refs/heads/feature/test {"0" * 40} refs/heads/feature/test {"1" * 40}\n')

    def test_execute_checks_and_test_before_push_without_auto_staging(self):
        body = self.authorize()
        self.write('README.md', '# Reviewed change\n')
        self.run_git('add', 'README.md')
        plan = publisher.prepare(self.root, 'feature/test', body, 'Message', 'Title')
        calls = []
        def fake_command(root, args, **kwargs):
            calls.append(args)
            if args[:3] == ['gh', 'repo', 'view']:
                return b'{"nameWithOwner":"example/project"}'
            if args[:3] == ['gh', 'pr', 'list']:
                return b'[]'
            if args[:3] == ['gh', 'pr', 'create']:
                return b'https://github.com/example/project/pull/1\n'
            return b''
        with mock.patch.object(publisher.shutil, 'which', return_value='gh'), mock.patch.object(publisher, 'command', side_effect=fake_command):
            result = publisher.publish(self.root, plan, message='Message', title='Title', body_file=body)
        self.assertTrue(result['execute'])
        self.assertEqual(result['pull_request_url'], 'https://github.com/example/project/pull/1')
        pushes = [args for args in calls if args[:2] == ['git', 'push']]
        self.assertEqual(len(pushes), 1)
        self.assertIn('HEAD:refs/heads/feature/test', pushes[0])
        self.assertFalse(any('--force' in arg for args in calls for arg in args))
        self.assertFalse(any(args[:2] == ['git', 'add'] for args in calls))
        test_index = next(i for i, args in enumerate(calls) if 'unittest' in args)
        push_index = next(i for i, args in enumerate(calls) if args[:2] == ['git', 'push'])
        self.assertLess(test_index, push_index)
        image_index = next(i for i, args in enumerate(calls) if any(str(arg).endswith('check_pr_image.py') for arg in args))
        self.assertLess(test_index, image_index)
        self.assertLess(image_index, push_index)

    def test_failed_candidate_build_blocks_push_and_pr(self):
        body = self.authorize()
        self.write('README.md', '# Reviewed change\n')
        self.run_git('add', 'README.md')
        plan = publisher.prepare(self.root, 'feature/test', body, 'Message', 'Title')
        calls = []
        def fake_command(root, args, **kwargs):
            calls.append(args)
            if args[:3] == ['gh', 'repo', 'view']:
                return b'{"nameWithOwner":"example/project"}'
            if any(str(arg).endswith('check_pr_image.py') for arg in args):
                raise publisher.PublishError('Synthetic candidate failure')
            return b''
        with mock.patch.object(publisher.shutil, 'which', return_value='gh'), mock.patch.object(publisher, 'command', side_effect=fake_command):
            with self.assertRaises(publisher.PublishError):
                publisher.publish(self.root, plan, message='Message', title='Title', body_file=body)
        self.assertFalse(any(args[:2] == ['git', 'push'] or args[:3] == ['gh', 'pr', 'create'] for args in calls))

    def test_inputs_changed_by_image_check_stop_publication(self):
        body = self.authorize()
        self.write('README.md', '# Reviewed change\n')
        self.run_git('add', 'README.md')
        plan = publisher.prepare(self.root, 'feature/test', body, 'Message', 'Title')
        calls = []
        def fake_command(root, args, **kwargs):
            calls.append(args)
            if args[:3] == ['gh', 'repo', 'view']:
                return b'{"nameWithOwner":"example/project"}'
            if any(str(arg).endswith('check_pr_image.py') for arg in args):
                self.write('README.md', '# Unreviewed change\n')
            return b''
        with mock.patch.object(publisher.shutil, 'which', return_value='gh'), mock.patch.object(publisher, 'command', side_effect=fake_command):
            with self.assertRaises(publisher.PublishError):
                publisher.publish(self.root, plan, message='Message', title='Title', body_file=body)
        self.assertFalse(any(args[:2] == ['git', 'push'] for args in calls))

    def test_pr_text_changed_during_image_check_stops_publication(self):
        body = self.authorize()
        self.write('README.md', '# Reviewed change\n')
        self.run_git('add', 'README.md')
        plan = publisher.prepare(self.root, 'feature/test', body, 'Message', 'Title')
        calls = []
        def fake_command(root, args, **kwargs):
            calls.append(args)
            if args[:3] == ['gh', 'repo', 'view']:
                return b'{"nameWithOwner":"example/project"}'
            if any(str(arg).endswith('check_pr_image.py') for arg in args):
                body.write_text('Changed unreviewed PR text')
            return b''
        with mock.patch.object(publisher.shutil, 'which', return_value='gh'), mock.patch.object(publisher, 'command', side_effect=fake_command):
            with self.assertRaises(publisher.PublishError):
                publisher.publish(self.root, plan, message='Message', title='Title', body_file=body)
        self.assertFalse(any(args[:2] == ['git', 'push'] for args in calls))

    def test_failed_tests_prevent_commit_and_push(self):
        body = self.authorize()
        self.write('README.md', '# Reviewed change\n')
        self.run_git('add', 'README.md')
        plan = publisher.prepare(self.root, 'feature/test', body, 'Message', 'Title')
        calls = []
        def fake_command(root, args, **kwargs):
            calls.append(args)
            if args[:3] == ['gh', 'repo', 'view']:
                return b'{"nameWithOwner":"example/project"}'
            if 'unittest' in args:
                raise publisher.PublishError('Synthetic test failure')
            return b''
        with mock.patch.object(publisher.shutil, 'which', return_value='gh'), mock.patch.object(publisher, 'command', side_effect=fake_command):
            with self.assertRaises(publisher.PublishError):
                publisher.publish(self.root, plan, message='Message', title='Title', body_file=body)
        self.assertFalse(any(args[:2] in (['git', 'commit'], ['git', 'push']) for args in calls))


    def test_staging_changed_by_tests_stops_publication(self):
        body = self.authorize()
        self.write('README.md', '# Reviewed change\n')
        self.run_git('add', 'README.md')
        plan = publisher.prepare(self.root, 'feature/test', body, 'Message', 'Title')
        calls = []
        def fake_command(root, args, **kwargs):
            calls.append(args)
            if args[:3] == ['gh', 'repo', 'view']:
                return b'{"nameWithOwner":"example/project"}'
            if 'unittest' in args:
                self.write('README.md', '# Different staged content\n')
                self.run_git('add', 'README.md')
            return b''
        with mock.patch.object(publisher.shutil, 'which', return_value='gh'), mock.patch.object(publisher, 'command', side_effect=fake_command):
            with self.assertRaises(publisher.PublishError):
                publisher.publish(self.root, plan, message='Message', title='Title', body_file=body)
        self.assertFalse(any(args[:2] in (['git', 'commit'], ['git', 'push']) for args in calls))


    def test_unreviewed_examples_csv_fails_worktree_audit(self):
        self.write('examples/data/user-holdings.csv', 'synthetic,unreviewed\n')
        result = guard.scan_worktree(self.root)
        self.assertFalse(result['passed'])
        self.assertEqual(result['violations'][0]['path'], 'examples/data/user-holdings.csv')


    def test_worktree_scans_synthetic_data_subdirectory(self):
        self.write('examples/data/wealthsimple-holdings.csv', 'symbol,quantity\nEXAMPLE,1\n')
        result = guard.scan_worktree(self.root)
        self.assertTrue(result['passed'])
        self.assertIn('examples/data/wealthsimple-holdings.csv', {item['path'] for item in result['files']})
        self.write('examples/data/wealthsimple-holdings.csv', 'ghp_' + 'a' * 36)
        self.assertFalse(guard.scan_worktree(self.root)['passed'])



class TypedSchemaPrivacyTests(unittest.TestCase):
    def test_secretstr_field_declarations_do_not_hide_literal_credentials(self):
        schema = b'class Login:\n    password: SecretStr = Field(min_length=1, max_length=256)\n'
        self.assertEqual(guard.content_issues(schema, 'src/wealth_ledger/web/api.py'), [])
        raw = b'class Login:\n    password: SecretStr = Field(default="not-a-public-credential")\n'
        self.assertIn('possible credential assignment', guard.content_issues(raw, 'src/wealth_ledger/web/api.py'))

    def test_prompted_password_reader_does_not_allow_a_quoted_credential(self):
        source = b'password = getpass.getpass("Owner password: ")\n'
        self.assertEqual(guard.content_issues(source, 'docs/web-operations.md'), [])
        quoted = b'password = "getpass.getpass("\n'
        self.assertIn('possible credential assignment', guard.content_issues(quoted, 'docs/web-operations.md'))

class AdoptionPrivacyTests(unittest.TestCase):
    def test_private_adoption_plan_content_is_rejected_even_under_a_public_path(self):
        import json
        marker='wealth-ledger-private-'+'adoption'
        raw=json.dumps({'format':marker,'source_root':'/example/private-ledger'}).encode()
        self.assertTrue(any('adoption' in message for message in guard.content_issues(raw,'examples/data/fx.json')))


if __name__ == '__main__':
    unittest.main()
