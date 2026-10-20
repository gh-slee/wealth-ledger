"""Reusable author checks reject contract drift without claiming financial booking."""
from dataclasses import replace
import unittest

from test_source_protocol import batch, HOLDING, INFO, RAW, EVIDENCE, KEY, AT, ACCOUNT, BTC, CAD
from wealth_ledger.source_protocol import Detection, CashFlow, Money, CryptoTransaction, CryptoLeg
from wealth_ledger.source_testing import check_contract, check_rejected, record_index
from decimal import Decimal


class Adapter:
    info = INFO
    def detect(self, raw):
        return Detection(True, "2024-v1", "Synthetic fixture")
    def normalize(self, raw, *, export_version):
        return batch(HOLDING)


class AuthorToolkitTests(unittest.TestCase):
    def test_reproducibility_and_source_identity_index(self):
        result = check_contract(Adapter(), RAW)
        self.assertEqual(result.record_count, 1)
        self.assertEqual(record_index(batch(HOLDING), RAW)[(ACCOUNT, "holdings", KEY.source_id)], HOLDING)
        with self.assertRaises(ValueError):
            record_index(batch(HOLDING, HOLDING), RAW)

    def test_wrong_metadata_version_hash_and_nondeterminism_fail(self):
        class Wrong(Adapter):
            def normalize(self, raw, *, export_version):
                return replace(batch(HOLDING), adapter=replace(INFO, adapter_version="other"))
        with self.assertRaises(AssertionError):
            check_contract(Wrong(), RAW)
        class Moving(Adapter):
            calls = 0
            def normalize(self, raw, *, export_version):
                self.calls += 1
                return batch(replace(HOLDING, quantity=Decimal(self.calls)))
        with self.assertRaises(AssertionError):
            check_contract(Moving(), RAW)
        with self.assertRaises(ValueError):
            check_contract(Adapter(), b"wrong bytes")
        check_rejected(Adapter(), b"wrong bytes", export_version="2024-v1")
        with self.assertRaises(AssertionError):
            check_rejected(Adapter(), RAW, export_version="2024-v1")

    def test_implementation_bugs_are_not_format_rejections(self):
        class Broken(Adapter):
            def normalize(self, raw, *, export_version):
                raise RuntimeError("Bug")
        with self.assertRaises(RuntimeError):
            check_rejected(Broken(), RAW, export_version="2024-v1")

    def test_transfer_scope_unknown_fee_and_revision_fixtures(self):
        transfer = CashFlow(KEY, AT, "transfer", Money(Decimal("10"), "CAD"), "completed", "unclassified", "demo-transfer")
        crypto = CryptoTransaction(KEY, AT, "swap", "completed", (
            CryptoLeg(ACCOUNT, BTC, Decimal("0.00100000")),), fees=None, transfer_reference="demo-swap")
        class Fixture(Adapter):
            record = transfer
            def normalize(self, raw, *, export_version):
                return batch(self.record)
        adapter = Fixture()
        check_contract(adapter, RAW)
        adapter.record = replace(transfer, transfer_reference=None)
        check_rejected(adapter, RAW, export_version="2024-v1")
        adapter.record = crypto
        check_contract(adapter, RAW)
        adapter.record = replace(crypto, legs=(CryptoLeg(ACCOUNT, BTC, Decimal("0.000000001")),))
        check_rejected(adapter, RAW, export_version="2024-v1")
        adapter.record = replace(HOLDING, key=replace(KEY, revision="2", supersedes_revision="1", change="correction"))
        check_contract(adapter, RAW)
        adapter.record = replace(adapter.record, key=replace(KEY, change="void"))
        check_rejected(adapter, RAW, export_version="2024-v1")
