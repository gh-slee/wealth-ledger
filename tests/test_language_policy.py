"""Bounded language checks use isolated synthetic files, not personal workspaces."""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_language


class LanguagePolicyTests(unittest.TestCase):
    def test_english_documents_allow_normal_unicode_punctuation(self):
        self.assertEqual(check_language.check_file('README.md', '# Guide\nUse Decimal \u2014 never guess.\n'), [])

    def test_cjk_markdown_reports_location_without_echoing_text(self):
        result = check_language.check_file('docs/user-manual.md', '# Guide\n\u4e2d\u6587\n')
        self.assertEqual(result[0]['line'], 2)
        self.assertEqual(result[0]['kind'], 'markdown')
        self.assertNotIn('\u4e2d', str(result))

    def test_comments_docstrings_and_identifiers_are_checked(self):
        source = '"""\u4e2d\u6587"""\n# \u4e2d\u6587\n\u6578\u91cf = 1\n'
        self.assertEqual({row['kind'] for row in check_language.check_file('scripts/example.py', source)},
                         {'docstring', 'comment', 'identifier'})

    def test_localized_runtime_and_test_strings_are_preserved(self):
        source = 'label = "\u4e2d\u6587"\n'
        self.assertEqual(check_language.check_file('src/wealth_ledger/example.py', source), [])
        self.assertEqual(check_language.check_file('tests/test_example.py', source), [])

    def test_private_guidance_and_catalogs_are_not_read_as_english_docs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'README.md').write_text('# Public guide\n', encoding='utf-8')
            (root / 'AGENTS.override.md').write_text('\u4e2d\u6587', encoding='utf-8')
            (root / 'private').mkdir()
            (root / 'private/notes.md').write_text('\u4e2d\u6587', encoding='utf-8')
            (root / 'src/wealth_ledger/locales').mkdir(parents=True)
            (root / 'src/wealth_ledger/locales/zh-TW.json').write_text('{"label":"\u4e2d\u6587"}', encoding='utf-8')
            result = check_language.scan(root)
            self.assertTrue(result['passed'])
            self.assertEqual(result['files_checked'], 1)
            (root / 'README.md').write_text('# \u4e2d\u6587\n', encoding='utf-8')
            self.assertFalse(check_language.scan(root)['passed'])

    def test_invalid_python_and_empty_scope_fail_closed(self):
        with self.assertRaises(check_language.LanguageError):
            check_language.check_file('scripts/example.py', 'def incomplete(')
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(check_language.LanguageError):
                check_language.scan(Path(directory))

    def test_cli_exit_codes_distinguish_pass_violation_and_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(check_language.main(['--root', directory]), 2)
                (root / 'README.md').write_text('# Guide\n', encoding='utf-8')
                self.assertEqual(check_language.main(['--root', directory]), 0)
                (root / 'README.md').write_text('# \u4e2d\u6587\n', encoding='utf-8')
                self.assertEqual(check_language.main(['--root', directory]), 1)

    def test_public_symlink_is_rejected_without_reading_its_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'private').mkdir()
            target = root / 'private/notes.md'
            target.write_text('Private synthetic text.', encoding='utf-8')
            try:
                (root / 'README.md').symlink_to(target)
            except OSError:
                self.skipTest('Symlinks unavailable on this platform')
            with self.assertRaises(check_language.LanguageError):
                check_language.scan(root)


if __name__ == '__main__':
    unittest.main()
