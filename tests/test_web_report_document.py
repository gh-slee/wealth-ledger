"""Web reading preserves published text, safe chart bindings and frozen finances."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

import test_web as foundation
from test_web import AVAILABLE
from test_web_reports import synthetic_payload, publish_fixture

if AVAILABLE:
    from wealth_ledger.web.report_document import parse_document, edition_metadata


@unittest.skipUnless(AVAILABLE, "Optional Web dependencies are not installed")
class DocumentTests(unittest.TestCase):
    setUp = foundation.WebTests.setUp
    bootstrap = foundation.WebTests.bootstrap
    login = foundation.WebTests.login
    mutate = foundation.WebTests.mutate
    portfolio = foundation.WebTests.portfolio

    def prepare(self, text=None):
        self.login(); self.pid = self.portfolio()
        _, self.project = self.store.portfolio(self.pid)
        self.payload = synthetic_payload(self.project)
        self.payload["reporting"] = {"locale": "en-CA"}
        self.report, self.file = publish_fixture(self.store, self.pid, self.payload)
        self.folder = self.file.parent
        self.url = f"/api/v1/portfolios/{self.pid}/reports/{self.report}/document"
        self.markdown = self.folder / "report.md"
        self.markdown.write_text(text or "# Investment report\n\n## Overview\n\n| Currency | Value |\n| --- | --- |\n| CAD | 1,930.00 |\n\n![Saved overview](charts/01_account_values.png)\n\n## Methods\n\nUnknown is not zero.\n")
        self.store.register_artifact(self.pid, self.report, self.markdown.relative_to(self.project).as_posix())

    def test_full_presentation_matches_saved_markdown_three_locales_without_rendering(self):
        self.prepare()
        from wealth_ledger.reporting import generate_reports
        for locale in ("en-CA", "zh-TW", "zh-CN"):
            with self.subTest(locale=locale):
                report, file = publish_fixture(self.store, self.pid, {**self.payload, "reporting": {"locale": locale}})
                # Only invented data is rendered here; the API must never render it.
                artifacts = generate_reports(self.payload, file.parent, locale=locale)
                for name in ["report.md", "report.pdf", *[str(Path(path).relative_to(file.parent)) for path in artifacts["charts"].values()]]:
                    self.store.register_artifact(self.pid, report, (file.parent/name).relative_to(self.project).as_posix())
                before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in file.parent.rglob("*") if path.is_file()}
                with patch("wealth_ledger.reporting.generate_reports", side_effect=AssertionError("No rendering")), patch("urllib.request.urlopen", side_effect=AssertionError("No network")):
                    response = self.client.get(self.url.replace(self.report, report))
                self.assertEqual(response.status_code, 200, response.text)
                document = response.json()
                self.assertEqual(document["locale"], locale)
                self.assertGreaterEqual(len(document["sections"]), 12)
                text = (file.parent/"report.md").read_text()
                for section in document["sections"]:
                    self.assertIn("## "+section["title"], text)
                    for block in section["blocks"]:
                        if block["kind"] == "chart":
                            self.assertIsNotNone(block["artifact_id"])
                        elif block["kind"] == "table":
                            self.assertTrue(all(len(row)==len(block["headers"]) for row in block["rows"]))
                self.assertNotIn(str(self.project), response.text)
                self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before})

    def test_text_only_grammar_and_exact_report_chart_scope(self):
        hostile = '<img src=x onerror="alert(1)">'
        self.prepare("# Report\n\n## Overview\n\n"+hostile+"\n\n![Outside](https://example.invalid/image.png)\n\n![Traversal](charts/../secret.png)\n\n| Name | Value |\n| --- | --- |\n| A \\| B | 0.00000001 |\n\n![Local](charts/01_account_values.png)\n")
        # A matching filename registered to another report must never be linked.
        other, _ = publish_fixture(self.store, self.pid, self.payload)
        wrong = self.project / "reports" / other / "charts/01_account_values.png"
        wrong.parent.mkdir(parents=True); wrong.write_bytes(b"synthetic PNG stand-in")
        wrong_id = self.store.register_artifact(self.pid, other, wrong.relative_to(self.project).as_posix())
        doc = self.client.get(self.url).json()
        blocks = doc["sections"][0]["blocks"]
        self.assertEqual(blocks[0]["text"], hostile)
        self.assertEqual(blocks[1]["kind"], "paragraph")
        self.assertEqual(blocks[2]["kind"], "paragraph")
        self.assertEqual(blocks[3]["rows"], [["A | B", "0.00000001"]])
        self.assertIsNone(blocks[4]["artifact_id"])
        local = self.folder / "charts/01_account_values.png"
        local.parent.mkdir(); local.write_bytes(b"synthetic PNG stand-in")
        local_id = self.store.register_artifact(self.pid, self.report, local.relative_to(self.project).as_posix())
        resolved = self.client.get(self.url).json()["sections"][0]["blocks"][-1]
        self.assertEqual(resolved["artifact_id"], local_id)
        self.assertNotEqual(resolved["artifact_id"], wrong_id)
        local.write_bytes(b"changed")
        self.assertEqual(self.client.get(f"/api/v1/portfolios/{self.pid}/artifacts/{local_id}").status_code, 409)

    def test_ownership_unpublished_integrity_and_missing_document(self):
        self.prepare()
        other = self.portfolio("Other synthetic scope")
        self.assertEqual(self.client.get(self.url.replace(self.pid, other)).status_code, 404)
        unpublished, _ = publish_fixture(self.store, self.pid, self.payload, status="data_committed")
        self.assertEqual(self.client.get(self.url.replace(self.report, unpublished)).status_code, 404)
        missing, _ = publish_fixture(self.store, self.pid, self.payload)
        self.assertEqual(self.client.get(self.url.replace(self.report, missing)).json()["error"]["code"], "report_document_unavailable")
        self.markdown.write_text("changed")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(str(self.project), response.text)
        self.mutate("POST", "/api/v1/auth/logout")
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_scope_metadata_uses_frozen_scope_not_dates_or_output_directory(self):
        self.prepare()
        a = edition_metadata(self.payload, "reports/date/r01/data.json")
        b = edition_metadata(self.payload, "reports/date/r02/data.json")
        self.assertEqual(a["scope_key"], b["scope_key"])
        self.assertEqual(b["edition_label"], "r02")
        c = edition_metadata({**self.payload, "meta": {**self.payload["meta"], "scope_id": "different"}}, "reports/date/r03/data.json")
        self.assertNotEqual(a["scope_key"], c["scope_key"])
        self.assertNotIn("account_id", a)
        self.assertEqual(a["report_locale"], "en-CA")

    def test_document_limits_and_bad_tables_fail_closed(self):
        from wealth_ledger.web.report_document import MAX_DOCUMENT_BYTES
        with self.assertRaises(ValueError):
            parse_document("## Section\n| A | B |\n| --- | --- |\n| too few |", {})
        with self.assertRaises(ValueError):
            parse_document("\n".join("## Heading" for _ in range(129)), {})
        self.prepare()
        with self.store.transaction() as conn:
            conn.execute("UPDATE artifacts SET byte_size=? WHERE report_id=? AND relative_path LIKE '%/report.md'", (MAX_DOCUMENT_BYTES+1,self.report))
        self.assertEqual(self.client.get(self.url).json()["error"]["code"], "report_document_unavailable")
