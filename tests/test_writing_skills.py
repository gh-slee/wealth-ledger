"""Writing bootstrap tests use synthetic text, mocked transport and temporary roots."""
from concurrent.futures import ThreadPoolExecutor
import contextlib
import io
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('writing_setup', Path(__file__).resolve().parents[1] / 'scripts/setup_writing_skills.py')
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)
COMMIT = 'a' * 40


def fake_get(url):
    if url.endswith('/commits/HEAD'):
        return json.dumps({'sha': COMMIT}).encode()
    if url.endswith('/SKILL.md'):
        name = 'caveman' if 'JuliusBrussee/caveman/' in url else 'humanizer'
        return ('---\nname: ' + name + '\ndescription: Synthetic writing guidance.\n---\nUse plain text.\n').encode()
    return b'Synthetic upstream license or notice.\n'


class WritingSetupTests(unittest.TestCase):
    def test_offline_check_never_writes_or_fetches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(setup, 'fetch', side_effect=AssertionError('No network')):
                result = setup.setup(root, ensure=False, get=lambda _: self.fail('No network'))
            self.assertFalse(result['ready'])
            self.assertEqual([row['status'] for row in result['skills']], ['missing', 'missing'])
            self.assertEqual(list(root.iterdir()), [])

    def test_missing_skills_use_latest_head_and_consistent_commit_with_licenses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requests = []
            def get(url):
                requests.append(url)
                return fake_get(url)
            result = setup.setup(root, ensure=True, get=get)
            self.assertTrue(result['ready'])
            self.assertEqual(sum(url.endswith('/commits/HEAD') for url in requests), 2)
            self.assertTrue(all('/' + COMMIT + '/' in url for url in requests if '/commits/' not in url))
            for name, source in setup.SOURCES.items():
                target = root / '.agents/skills' / name
                receipt = json.loads((target / '_origin.json').read_text())
                self.assertEqual(receipt['commit'], COMMIT)
                self.assertEqual(set(receipt['files_sha256']), set(source['files']))
                for filename, digest in receipt['files_sha256'].items():
                    self.assertEqual(hashlib.sha256((target / filename).read_bytes()).hexdigest(), digest)

    def test_existing_copies_are_never_overwritten_or_looked_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            setup.setup(root, ensure=True, get=fake_get)
            target = root / '.agents/skills/caveman/SKILL.md'
            target.write_bytes(target.read_bytes() + b'Locally reviewed extension.\n')
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            for ensure in (False, True):
                result = setup.setup(root, ensure=ensure, get=lambda _: self.fail('Existing copies must use no network'))
                self.assertTrue(result['ready'])
                self.assertTrue(all(row['status'] == 'present' for row in result['skills']))
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_only_missing_skill_fetches_a_newer_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = setup.skill_parent(root, create=True)
            setup.install(parent, 'caveman', fake_get)
            requests = []
            def get(url):
                requests.append(url)
                if url.endswith('/commits/HEAD'):
                    return json.dumps({'sha': 'b' * 40}).encode()
                return fake_get(url)
            result = setup.setup(root, ensure=True, get=get)
            self.assertTrue(result['ready'])
            self.assertTrue(all('blader/humanizer/' in url for url in requests))
            self.assertEqual(json.loads((parent/'caveman/_origin.json').read_text())['commit'], COMMIT)
            self.assertEqual(json.loads((parent/'humanizer/_origin.json').read_text())['commit'], 'b' * 40)

    def test_failed_download_leaves_no_partial_skill_and_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def fail(url):
                if url.endswith('/LICENSE'):
                    raise OSError('Synthetic network interruption')
                return fake_get(url)
            with self.assertRaises(OSError):
                setup.setup(root, ensure=True, get=fail)
            parent = root / '.agents/skills'
            self.assertEqual(list(parent.iterdir()), [])
            self.assertTrue(setup.setup(root, ensure=True, get=fake_get)['ready'])

    def test_unexpected_commit_or_skill_metadata_is_rejected_before_publication(self):
        for bad in (b'{"sha":"main"}', b'{"sha":"../unsafe"}', b'[]', b'not-json'):
            with self.subTest(metadata=bad), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises((ValueError, setup.SetupError)):
                    setup.setup(Path(directory), ensure=True, get=lambda _: bad)
                self.assertFalse((Path(directory)/'.agents/skills/caveman').exists())
        for bad in (b'not frontmatter', b'---\nname: another\ndescription: Wrong.\n---\n',
                    b'---\nname: caveman\n---\n', b'\xff', b'a\0b', b'x' * (setup.MAX_BYTES + 1)):
            with self.subTest(skill=bad[:30]), tempfile.TemporaryDirectory() as directory:
                def get(url):
                    return bad if url.endswith('/SKILL.md') else fake_get(url)
                with self.assertRaises(setup.SetupError):
                    setup.setup(Path(directory), ensure=True, get=get)
                self.assertFalse((Path(directory)/'.agents/skills/caveman').exists())

    def test_symlink_components_or_existing_incomplete_directories_are_not_touched(self):
        for relative in ('.agents', '.agents/skills', '.agents/skills/caveman', '.agents/skills/caveman/SKILL.md'):
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                outside = root / 'private-target'
                outside.mkdir()
                marker = outside / 'marker'
                marker.write_text('Preserve this synthetic private target.')
                link = root / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(outside, target_is_directory=True)
                with self.assertRaises(setup.SetupError):
                    setup.setup(root, ensure=True, get=lambda _: self.fail('No network through symlinks'))
                self.assertEqual(marker.read_text(), 'Preserve this synthetic private target.')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.agents/skills/caveman').mkdir(parents=True)
            with self.assertRaises(setup.SetupError):
                setup.setup(root, ensure=True, get=lambda _: self.fail('Preserve partial copies'))

    def test_concurrent_setups_publish_complete_copies_and_leave_no_staging_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            barrier = threading.Barrier(2)
            def get(url):
                if 'JuliusBrussee/caveman/commits/HEAD' in url:
                    barrier.wait(timeout=5)
                return fake_get(url)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(setup.setup, root, ensure=True, get=get) for _ in range(2)]
                self.assertTrue(all(f.result(timeout=10)['ready'] for f in futures))
            parent = root / '.agents/skills'
            self.assertEqual({p.name for p in parent.iterdir()}, set(setup.SOURCES))
            for name in setup.SOURCES:
                receipt = json.loads((parent/name/'_origin.json').read_text())
                for filename, digest in receipt['files_sha256'].items():
                    self.assertEqual(hashlib.sha256((parent/name/filename).read_bytes()).hexdigest(), digest)

    def test_cli_reports_readiness_and_redacts_transport_details(self):
        for ready, expected in ((False, 1), (True, 0)):
            output = io.StringIO()
            with mock.patch.object(setup, 'setup', return_value={'ready': ready}), contextlib.redirect_stdout(output):
                self.assertEqual(setup.main(['--check']), expected)
            self.assertEqual(json.loads(output.getvalue())['ready'], ready)
        output = io.StringIO()
        with mock.patch.object(setup, 'setup', side_effect=OSError('Synthetic provider response body')), contextlib.redirect_stdout(output):
            self.assertEqual(setup.main(['--ensure']), 2)
        self.assertNotIn('Synthetic provider response body', output.getvalue())

    def test_redirects_are_refused(self):
        with self.assertRaises(setup.SetupError):
            setup.NoRedirect().redirect_request(None, None, 302, 'redirect', {}, 'https://example.invalid')


if __name__ == '__main__':
    unittest.main()
