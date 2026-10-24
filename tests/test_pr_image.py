"""PR candidate failure/privacy gates use a disposable Git tree and fake Docker."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_pr_image as candidate
from docker_context import FIXED


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for name in FIXED:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        (self.root / '.gitignore').write_text('/work/\n/private/\n/data/\n')
        source = self.root / 'src/wealth_ledger'
        source.mkdir(parents=True)
        (source / '__init__.py').write_text('"""Synthetic candidate."""\n')
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Synthetic')
        self.git('config', 'user.email', 'example@users.noreply.github.com')
        self.git('add', '.')
        self.git('commit', '-m', 'Synthetic candidate')
        self.calls = []

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def fake_docker(self, args, output, **kwargs):
        self.calls.append(args)
        if args[1] == 'build':
            self.labels = dict(value.split('=', 1) for i, value in enumerate(args) if args[i-1] == '--label')
        if args[1:3] == ['image', 'inspect']:
            return json.dumps([{'Id': 'sha256:'+'a'*64, 'Config': {'User': '10001:10001', 'Labels': self.labels}}])
        if args[1] == 'run':
            return json.dumps({'health': True, 'browser_assets': True, 'anonymous_api_401': True,
                               'worker_once': True, 'architecture': 'synthetic'})
        return ''

    def execute(self, runner=None):
        # Actual Docker is never invoked by unit tests, including cleanup.
        real_run = subprocess.run
        def isolated_run(args, **kwargs):
            if args[0] == 'docker':
                self.assertEqual(args[1:3], ['rm', '--force'])
                return subprocess.CompletedProcess(args, 0)
            return real_run(args, **kwargs)
        with mock.patch.object(candidate, 'run', side_effect=runner or self.fake_docker), mock.patch.object(candidate.subprocess, 'run', side_effect=isolated_run):
            return candidate.check(self.root)

    def test_candidate_receipt_matches_commit_and_has_no_host_mounts_or_ports(self):
        for name in ('data/holdings.csv', 'private/notes.md', 'AGENTS.override.md'):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('Synthetic private evidence')
        # A normal checkout ignores the private override too.
        with (self.root / '.git/info/exclude').open('a') as f:
            f.write('\nAGENTS.override.md\n')
        receipt = self.execute()
        self.assertEqual(receipt['head'], self.git('rev-parse', 'HEAD'))
        self.assertEqual(json.loads((self.root / receipt['receipt']).read_text()), receipt)
        runtime = next(c for c in self.calls if c[1] == 'run')
        self.assertIn('none', runtime)
        self.assertIn('--read-only', runtime)
        self.assertNotIn('--publish', runtime)
        self.assertNotIn('--volume', runtime)
        self.assertNotIn('--mount', runtime)
        self.assertIn(receipt['image_id'], runtime)
        context = self.root / receipt['receipt'].replace('receipt.json', 'context')
        self.assertFalse((context / 'data').exists())
        self.assertFalse((context / 'private').exists())
        self.assertFalse((context / 'AGENTS.override.md').exists())
        self.assertEqual(sum(c[1]=='build' for c in self.calls), 1)

    def test_dirty_tracked_tree_stops_before_build(self):
        (self.root / 'LICENSE').write_text('Changed synthetic file')
        with self.assertRaisesRegex(ValueError, 'Commit reviewed'):
            self.execute()
        self.assertFalse(self.calls)

    def test_untracked_image_source_stops_before_docker(self):
        (self.root / 'src/wealth_ledger/unreviewed.py').write_text('# Synthetic extra\n')
        with self.assertRaisesRegex(ValueError, 'uncommitted'):
            self.execute()
        self.assertFalse(self.calls)

    def test_build_and_smoke_failure_never_write_success_receipt(self):
        for phase in ('build', 'run'):
            def failed(args, output, **kwargs):
                if args[1] == phase:
                    raise RuntimeError('Synthetic build/runtime failure')
                return self.fake_docker(args, output, **kwargs)
            with self.assertRaises(RuntimeError):
                self.execute(failed)
        self.assertFalse(list((self.root / 'work').rglob('receipt.json')))

    def test_source_change_during_build_invalidates_success(self):
        def changed(args, output, **kwargs):
            value = self.fake_docker(args, output, **kwargs)
            if args[1] == 'run':
                (self.root / 'LICENSE').write_text('Different synthetic source')
            return value
        with self.assertRaisesRegex(ValueError, 'Commit reviewed'):
            self.execute(changed)
        self.assertFalse(list((self.root / 'work').rglob('receipt.json')))

    def test_root_image_identity_or_missing_smoke_evidence_is_rejected(self):
        for broken in ('user', 'smoke'):
            def invalid(args, output, **kwargs):
                value = self.fake_docker(args, output, **kwargs)
                if broken == 'user' and args[1:3] == ['image', 'inspect']:
                    metadata = json.loads(value); metadata[0]['Config']['User'] = '0:0'
                    return json.dumps(metadata)
                if broken == 'smoke' and args[1] == 'run':
                    return '{}'
                return value
            with self.assertRaises(ValueError):
                self.execute(invalid)
        self.assertFalse(list((self.root / 'work').rglob('receipt.json')))

    def test_evidence_symlink_is_rejected(self):
        target = self.root / 'outside'; target.mkdir()
        (self.root / 'work').symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            self.execute()
        self.assertFalse(list(target.iterdir()))
