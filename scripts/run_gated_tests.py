#!/usr/bin/env python3
"""Run an opt-in unittest suite and fail when it skips an unexpected number of tests.

CI jobs that exist to run gated suites (real PostgreSQL, Docker images) pass
only when the suite reports exactly the skip count the job expects. A missing
opt-in variable then fails the job instead of leaving every gated test skipped.

Usage:
    python scripts/run_gated_tests.py --expect-skipped 0 -- discover -s tests -p 'test_x.py'
    python scripts/run_gated_tests.py --expect-skipped 3 -- test_module test_other.Case

Arguments after ``--`` are passed to ``python -m unittest`` unchanged. The
script uses only the standard library.
"""
from __future__ import annotations

import argparse
from collections import Counter
import os
from pathlib import Path
import sys
import unittest

SCRIPT_DIRECTORY = Path(__file__).resolve().parent


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--expect-skipped', type=int, required=True,
                        help='exact number of skipped tests this suite must report')
    parser.add_argument('unittest_args', nargs=argparse.REMAINDER,
                        help='arguments for python -m unittest, after --')
    options = parser.parse_args(argv)
    if options.expect_skipped < 0:
        parser.error('--expect-skipped must not be negative')
    if options.unittest_args[:1] == ['--']:
        options.unittest_args = options.unittest_args[1:]
    if not options.unittest_args:
        parser.error('give the unittest arguments after --')
    return options


def run_suite(unittest_args: list[str], stream=None) -> unittest.TestResult:
    """Run unittest exactly as ``python -m unittest <args> -v`` would and return the result."""
    output = stream or sys.stderr

    # TestProgram applies -f, -b, -c and --locals only when given a runner class.
    class Runner(unittest.TextTestRunner):
        def __init__(self, **options):
            super().__init__(stream=output, **options)

    runner = Runner
    program = unittest.TestProgram(module=None, argv=['python -m unittest', *unittest_args],
                                   testRunner=runner, exit=False, verbosity=2)
    return program.result


def skip_summary(result: unittest.TestResult) -> list[str]:
    """Group skips by reason so a log shows why tests did not run."""
    reasons = Counter(reason for _test, reason in result.skipped)
    return ['  {} x {}'.format(count, reason) for reason, count in sorted(reasons.items())]


def check(result: unittest.TestResult, expected: int) -> list[str]:
    """Return guard failures; an empty list means the suite ran as expected."""
    failures = []
    skipped = len(result.skipped)
    if result.testsRun == 0:
        failures.append('no tests ran')
    elif result.testsRun == skipped:
        failures.append('every test was skipped')
    if skipped != expected:
        failures.append('expected {} skipped, got {}'.format(expected, skipped))
    return failures


def main(argv: list[str] | None = None) -> int:
    options = parse_arguments(sys.argv[1:] if argv is None else argv)
    # Running this file puts scripts/ first on sys.path; drop it so script
    # modules cannot shadow test or application modules of the same name.
    sys.path[:] = [entry for entry in sys.path
                   if Path(entry or '.').resolve() != SCRIPT_DIRECTORY]
    # Like python -m unittest, find named test modules in the working directory.
    sys.path.insert(0, os.getcwd())
    result = run_suite(options.unittest_args)
    skipped = len(result.skipped)
    print('Skip guard: {} run, {} skipped (expected {}), {} failed, {} errors'.format(
        result.testsRun, skipped, options.expect_skipped, len(result.failures), len(result.errors)))
    for line in skip_summary(result):
        print(line)
    failures = check(result, options.expect_skipped)
    for failure in failures:
        print('Skip guard failed: ' + failure, file=sys.stderr)
    return 0 if result.wasSuccessful() and not failures else 1


if __name__ == '__main__':
    sys.exit(main())
