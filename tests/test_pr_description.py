"""PR format checks use synthetic descriptions; no GitHub or financial data."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_pr_description as pr_format

TEMPLATE = pr_format.TEMPLATE.read_text(encoding='utf-8')


def valid_body():
    return '''## Change Summary

A synthetic change makes the sample behavior explicit.

- Add the first meaningful example behavior.
- Preserve the second documented behavior.

## Files Changed

- `README.md`: Explain the synthetic change.

## Testing & Evidence

### Local Verification

- NOT RUN: Synthetic fixture only.

### CI Verification

- NOT RUN: No remote run exists for this fixture.

### Independent QA / Architecture Review

- NOT RUN: No independent review was requested for this fixture.

### Required Pre-PR Validation

- NOT RUN: Synthetic fixture; no image was built.
'''


class PrDescriptionTests(unittest.TestCase):
    def test_small_complete_body_and_all_explicit_result_states_are_valid(self):
        for status in ('PASS', 'FAIL', 'NOT RUN'):
            with self.subTest(status=status):
                self.assertEqual(pr_format.validate(valid_body().replace('NOT RUN', status), TEMPLATE), [])

    def test_pending_is_a_ci_status_not_a_completed_local_check(self):
        body = valid_body().replace('- NOT RUN: No remote run exists for this fixture.', '- PENDING: Synthetic CI run is in progress.')
        self.assertEqual(pr_format.validate(body, TEMPLATE), [])
        self.assertTrue(pr_format.validate(valid_body().replace('- NOT RUN: Synthetic fixture only.', '- PENDING: Local check is still running.'), TEMPLATE))

    def test_plain_prose_and_missing_duplicate_or_reordered_required_sections_fail(self):
        good = valid_body()
        cases = [
            'A long narrative with no review structure.',
            good.replace('## Files Changed', '## Arbitrary Inventory'),
            good + '\n## Change Summary\nA duplicated section.\n',
            good[good.index('## Files Changed'):] + good[:good.index('## Files Changed')],
        ]
        for body in cases:
            with self.subTest(body=body[:60]):
                self.assertTrue(pr_format.validate(body, TEMPLATE))

    def test_summary_sentence_and_two_to_six_bullets_are_required(self):
        good = valid_body()
        for body in (good.replace('A synthetic change makes the sample behavior explicit.\n\n', ''),
                     good.replace('- Preserve the second documented behavior.\n', ''),
                     good.replace('## Files Changed', '- Extra.\n' * 5 + '\n## Files Changed')):
            self.assertTrue(pr_format.validate(body, TEMPLATE))

    def test_file_inventory_needs_formatted_paths_and_explanations(self):
        for row in ('- README.md: Changed.', '- `README.md`', '- No paths listed.'):
            self.assertTrue(pr_format.validate(valid_body().replace('- `README.md`: Explain the synthetic change.', row), TEMPLATE))
        body = valid_body().replace('- `README.md`:', '- `docs/`, `scripts/example.py`:')
        self.assertEqual(pr_format.validate(body, TEMPLATE), [])

    def test_evidence_categories_and_statuses_cannot_be_collapsed_into_prose(self):
        good = valid_body()
        for body in (good.replace('### CI Verification\n', ''),
                     good.replace('### Independent QA / Architecture Review', '### Developer Self Review'),
                     good.replace('- NOT RUN: Synthetic fixture only.', 'All checks look good.'),
                     good.replace('- NOT RUN: Synthetic fixture only.', '- <STATUS>: Add results later.')):
            self.assertTrue(pr_format.validate(body, TEMPLATE))

    def test_optional_sections_are_ordered_and_empty_placeholders_fail(self):
        self.assertEqual(pr_format.validate(valid_body() + '\n## Reviewer Focus\n\n- Review the changed behavior.\n', TEMPLATE), [])
        self.assertTrue(pr_format.validate(valid_body() + '\n## Screenshots / Visual Evidence\n\n', TEMPLATE))
        body = valid_body() + '\n## Reviewer Focus\n\n- Review behavior.\n\n## Behavior & Compatibility\n\n- Existing input remains accepted.\n'
        self.assertTrue(pr_format.validate(body, TEMPLATE))

    def test_fenced_or_commented_fake_headers_do_not_satisfy_the_format(self):
        good = valid_body()
        for body in ('```markdown\n' + good + '\n```', '<!--\n' + good + '\n-->', '<!--\n' + good):
            self.assertTrue(pr_format.validate(body, TEMPLATE))
        self.assertEqual(pr_format.validate(good + '\n```markdown\n## Unrelated Example\n```\n', TEMPLATE), [])

    def test_template_is_the_format_authority(self):
        changed = TEMPLATE.replace('Change Summary', 'Outcome Summary')
        self.assertEqual(pr_format.validate(valid_body().replace('Change Summary', 'Outcome Summary'), changed), [])
        with self.assertRaises(ValueError):
            pr_format.validate(valid_body(), '# Incomplete template')
        with self.assertRaises(ValueError):
            pr_format.validate(valid_body(), TEMPLATE.replace('### CI Verification', '### Local Verification'))
        self.assertTrue(pr_format.validate(TEMPLATE, TEMPLATE))

    def test_format_does_not_pretend_to_prove_factual_claims(self):
        # A shape check cannot authenticate a CI claim; human evidence review is separate.
        body = valid_body().replace('- NOT RUN: No remote run exists for this fixture.', '- PASS: A synthetic claim without a real CI run.')
        self.assertEqual(pr_format.validate(body, TEMPLATE), [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'body.md';path.write_text(body)
            result = pr_format.check(path)
            self.assertIn('no proof of factual accuracy', result['limitations'])

    def test_cli_distinguishes_valid_invalid_and_unreadable_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'body.md'
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pr_format.main(['--body-file', str(path)]), 2)
                path.write_text('Unstructured prose.')
                self.assertEqual(pr_format.main(['--body-file', str(path)]), 1)
                path.write_text(valid_body())
                self.assertEqual(pr_format.main(['--body-file', str(path)]), 0)


if __name__ == '__main__':
    unittest.main()
