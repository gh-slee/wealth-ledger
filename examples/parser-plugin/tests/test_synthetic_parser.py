"""Synthetic author acceptance; requires the independently installed plugin/core."""
import csv
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import io
import unittest
from unittest.mock import patch

from synthetic_parser import FIELDS, VERSION, SyntheticHoldings, register
from wealth_ledger.source_protocol import Holding
from wealth_ledger.source_registry import AdapterRegistration
from wealth_ledger.source_testing import check_contract, check_rejected, record_index


def fixture(**changes):
    row = dict(zip(FIELDS, (VERSION, "demo-account", "position-001", "r1", "", "original",
                            "2024-01-31T16:00:00-05:00", "DEMO", "XTSX", "CAD", "1.25", "125.00", "", "scope1")))
    row.update(changes)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader(); writer.writerow(row)
    return output.getvalue().encode()


class ExampleParserTests(unittest.TestCase):
    def setUp(self):
        self.adapter = SyntheticHoldings()

    def test_contract_and_shared_class_identity(self):
        result = check_contract(self.adapter, fixture())
        self.assertEqual((result.record_count, result.coverage_count), (1, 1))
        self.assertIsInstance(self.adapter.normalize(fixture(), export_version=VERSION).records[0], Holding)
        self.assertIsInstance(register(), AdapterRegistration)

    def test_bom_overlap_preserves_record_identity(self):
        first, second = fixture(), b"\xef\xbb\xbf" + fixture()
        batches = [self.adapter.normalize(raw, export_version=VERSION) for raw in (first, second)]
        self.assertEqual(record_index(batches[0], first), record_index(batches[1], second))
        self.assertNotEqual(batches[0].evidence.raw_sha256, batches[1].evidence.raw_sha256)

    def test_corrections_keep_source_id_and_explicit_revision(self):
        raw = fixture(revision="r2", supersedes="r1", change="correction", quantity="2.5")
        check_contract(self.adapter, raw)
        corrected = self.adapter.normalize(raw, export_version=VERSION).records[0]
        self.assertEqual(corrected.key.source_id, "position-001")
        self.assertEqual(corrected.key.supersedes_revision, "r1")
        self.assertEqual(corrected.quantity, Decimal("2.5"))
        check_rejected(self.adapter, fixture(change="correction"), export_version=VERSION)

    def test_unknown_and_zero_cost_are_distinct_and_scope_is_partial(self):
        batches = [self.adapter.normalize(fixture(cost=cost), export_version=VERSION) for cost in ("", "0")]
        self.assertIsNone(batches[0].records[0].cost)
        self.assertEqual(batches[1].records[0].cost.amount, Decimal(0))
        self.assertEqual(batches[0].coverage[0].status, "partial")

    def test_malformed_timezone_precision_currency_and_columns_reject(self):
        for changes in ({"as_of":"2024-01-31"}, {"quantity":"NaN"}, {"value":"Infinity"},
                        {"market":""}, {"currency":"cad"}, {"id":""}, {"scope_revision":""}):
            with self.subTest(changes=changes):
                check_rejected(self.adapter, fixture(**changes), export_version=VERSION)
        for raw in (b"not,a,format\n1,2,3", b"\xff", fixture() + fixture().split(b"\n", 1)[1]):
            check_rejected(self.adapter, raw, export_version=VERSION)

    def test_no_common_io_or_clock_dependencies(self):
        # A smoke check, not a sandbox or a proof of side-effect freedom.
        with patch("builtins.open", side_effect=AssertionError("No file IO")), \
             patch("socket.socket", side_effect=AssertionError("No network")), \
             patch("subprocess.Popen", side_effect=AssertionError("No subprocess")):
            check_contract(self.adapter, fixture())


if __name__ == "__main__":
    unittest.main()
