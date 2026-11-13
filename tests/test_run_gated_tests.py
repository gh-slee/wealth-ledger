"""Skip guard checks use synthetic throwaway test modules; no database or Docker."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'run_gated_tests.py'

GATED_MODULE = '''
import os
import unittest


class Always(unittest.TestCase):
    def test_runs(self):
        self.assertTrue(True)


@unittest.skipUnless(os.environ.get('SYNTHETIC_GATE') == '1', 'Synthetic opt-in gate')
class Gated(unittest.TestCase):
    def test_first(self):
        self.assertTrue(True)

    def test_second(self):
        self.assertTrue(True)
'''


class SkipGuardTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='skip-guard-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def write(self, name, source):
        (self.root / name).write_text(textwrap.dedent(source), encoding='utf-8')

    def run_guard(self, *args, gate=None):
        environment = {key: value for key, value in os.environ.items() if key != 'SYNTHETIC_GATE'}
        if gate is not None:
            environment['SYNTHETIC_GATE'] = gate
        environment['PYTHONPATH'] = str(self.root)
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.root, env=environment,
                              capture_output=True, text=True, timeout=60)

    def test_passes_when_the_gate_is_open_and_nothing_is_skipped(self):
        self.write('test_gated.py', GATED_MODULE)
        result = self.run_guard('--expect-skipped', '0', '--',
                                'discover', '-s', '.', '-p', 'test_gated.py', gate='1')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('Skip guard: 3 run, 0 skipped (expected 0), 0 failed, 0 errors', result.stdout)
        # Verbose unittest output stays visible in the job log.
        self.assertIn('test_first', result.stderr)

    def test_fails_when_the_opt_in_variable_is_missing(self):
        self.write('test_gated.py', GATED_MODULE)
        result = self.run_guard('--expect-skipped', '0', '--', 'discover', '-s', '.', '-p', 'test_gated.py')
        self.assertEqual(1, result.returncode)
        self.assertIn('expected 0 skipped, got 2', result.stderr)
        self.assertIn('2 x Synthetic opt-in gate', result.stdout)

    def test_passes_when_the_expected_skips_match(self):
        self.write('test_gated.py', GATED_MODULE)
        result = self.run_guard('--expect-skipped', '2', '--', 'discover', '-s', '.', '-p', 'test_gated.py')
        self.assertEqual(0, result.returncode, result.stderr)

    def test_fails_when_fewer_tests_skip_than_expected(self):
        self.write('test_gated.py', GATED_MODULE)
        result = self.run_guard('--expect-skipped', '2', '--',
                                'discover', '-s', '.', '-p', 'test_gated.py', gate='1')
        self.assertEqual(1, result.returncode)
        self.assertIn('expected 2 skipped, got 0', result.stderr)

    def test_a_failing_test_fails_even_with_the_expected_skips(self):
        self.write('test_broken.py', '''
            import unittest


            class Broken(unittest.TestCase):
                def test_fails(self):
                    self.assertEqual(1, 2)
        ''')
        result = self.run_guard('--expect-skipped', '0', '--', 'discover', '-s', '.', '-p', 'test_broken.py')
        self.assertEqual(1, result.returncode)
        self.assertIn('1 run, 0 skipped (expected 0), 1 failed', result.stdout)

    def test_fails_when_no_tests_are_found(self):
        result = self.run_guard('--expect-skipped', '0', '--', 'discover', '-s', '.', '-p', 'test_missing.py')
        self.assertEqual(1, result.returncode)
        self.assertIn('no tests ran', result.stderr)

    def test_fails_when_every_test_is_skipped(self):
        self.write('test_only_gated.py', '''
            import unittest


            @unittest.skip('Synthetic always skipped')
            class OnlyGated(unittest.TestCase):
                def test_one(self):
                    pass
        ''')
        result = self.run_guard('--expect-skipped', '1', '--',
                                'discover', '-s', '.', '-p', 'test_only_gated.py')
        self.assertEqual(1, result.returncode)
        self.assertIn('every test was skipped', result.stderr)

    def test_runs_named_modules_and_classes(self):
        self.write('test_gated.py', GATED_MODULE)
        result = self.run_guard('--expect-skipped', '0', '--', 'test_gated.Always', gate='1')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('Skip guard: 1 run, 0 skipped', result.stdout)

    def test_rejects_missing_or_negative_arguments(self):
        for args in (('--expect-skipped', '0'), ('--expect-skipped', '-1', '--', 'test_gated'),
                     ('--', 'test_gated')):
            with self.subTest(args=args):
                result = self.run_guard(*args)
                self.assertEqual(2, result.returncode)


if __name__ == '__main__':
    unittest.main()
