"""Offline synthetic acceptance for versioned normalization contracts, not a loader."""
from dataclasses import replace
from datetime import datetime
from decimal import Decimal as D
import hashlib
import json
import unittest

from wealth_ledger.source_protocol import (
    AccountKey, AssetKey, Money, RecordKey, Holding, CashFlow, CryptoLeg,
    CryptoTransaction, Coverage, SourceEvidence, AdapterInfo, Detection,
    NormalizedBatch, SourceAdapter, validate_batch, validate_info,
    resolve_detection, canonical_json,
)

AT = datetime.fromisoformat("2024-01-31T17:00:00-05:00")
RAW = b"synthetic source bytes"
ACCOUNT = AccountKey("synthetic", "account-001")
KEY = RecordKey(ACCOUNT, "position-001", "1")
INFO = AdapterInfo("synthetic", "synthetic.holdings", "1.0.0", ("2024-v1",),
                   ("holdings", "cash_flows", "crypto_transactions"))
STOCK = AssetKey("security", "DEMO", "CAD", market="XTSE", identifier="synthetic-isin")
BTC = AssetKey("crypto", "BTC", "CAD", network="bitcoin")
CAD = AssetKey("cash", "CAD", "CAD")
HOLDING = Holding(KEY, AT, STOCK, D("1.25"), Money(D("100"), "CAD"), None)
EVIDENCE = SourceEvidence(hashlib.sha256(RAW).hexdigest(), AT, AT, "synthetic-export", (), (), "stable provider ID")


def batch(*records):
    scopes = tuple(Coverage(kind, ACCOUNT, AT, AT, "partial", "synthetic declaration", "scope-001", "1")
                   for kind in sorted({r.kind for r in records}))
    return NormalizedBatch(INFO, "2024-v1", EVIDENCE, scopes, records)


class SourceProtocolTests(unittest.TestCase):
    def test_lossless_records_unknown_cost_and_explicit_scope(self):
        value = batch(HOLDING)
        validate_batch(value, RAW)
        data = json.loads(canonical_json(value))
        self.assertEqual(data["records"][0]["quantity"], "1.25")
        self.assertIsNone(data["records"][0]["cost"])
        self.assertEqual(data["records"][0]["as_of"], AT.isoformat())
        self.assertEqual(data["coverage"][0]["status"], "partial")
        with self.assertRaisesRegex(ValueError, "scope"):
            validate_batch(replace(value, coverage=()), RAW)
        validate_batch(replace(value, records=()), RAW)
        self.assertEqual(value.coverage[0].status, "partial")

    def test_float_nan_timezone_identity_and_satoshi_rejected(self):
        cases = [replace(HOLDING, quantity=1.25), replace(HOLDING, quantity=D("NaN")),
                 replace(HOLDING, as_of=AT.replace(tzinfo=None)),
                 replace(HOLDING, asset=replace(STOCK, market=None)),
                 replace(HOLDING, asset=replace(BTC, network=None)),
                 replace(HOLDING, asset=BTC, quantity=D("0.000000001")),
                 replace(HOLDING, market_value=Money(D(10), "USD")),
                 replace(HOLDING, key=replace(KEY, account=AccountKey("other", "account-001"))),
                 replace(HOLDING, key=replace(KEY, source_id=""))]
        for record in cases:
            with self.subTest(record=record), self.assertRaises(ValueError):
                validate_batch(batch(record), RAW)

    def test_raw_hash_capability_and_ambiguous_detection(self):
        with self.assertRaises(ValueError):
            validate_batch(batch(HOLDING), b"different source")
        for info in (replace(INFO, api_version=2), replace(INFO, api_version=True),
                     replace(INFO, kinds=("observed_balances",)), replace(INFO, kinds=("holdings", "holdings")),
                     replace(INFO, provider_id="Filename With Spaces")):
            with self.subTest(info=info), self.assertRaises(ValueError):
                validate_info(info)
        match = Detection(True, "2024-v1", "exact synthetic columns")
        self.assertEqual(resolve_detection(((INFO, match),)), (INFO, match))
        for candidates in ((), ((INFO, Detection(False, None, "unsupported")),),
                           ((INFO, match), (replace(INFO, adapter_id="other"), match)),
                           ((INFO, match), (INFO, match)),
                           ((INFO, Detection(True, "unknown-v2", "unexpected version")),)):
            with self.assertRaises(ValueError):
                resolve_detection(candidates)

    def test_revision_correction_void_and_duplicate_rules(self):
        correction = replace(HOLDING, key=replace(KEY, revision="2", supersedes_revision="1", change="correction"))
        validate_batch(batch(correction), RAW)
        for record in (replace(HOLDING, key=replace(KEY, change="correction")),
                       replace(HOLDING, key=replace(KEY, supersedes_revision="1")),
                       replace(correction, key=replace(correction.key, supersedes_revision="2"))):
            with self.assertRaises(ValueError):
                validate_batch(batch(record), RAW)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_batch(batch(HOLDING, correction), RAW)

    def test_cash_flow_transfer_unknown_boundary_not_a_contribution(self):
        flow = CashFlow(KEY, AT, "transfer", Money(D("10"), "CAD"), "completed", "unclassified", "transfer-001")
        validate_batch(batch(flow), RAW)
        self.assertEqual(json.loads(canonical_json(batch(flow)))["records"][0]["boundary"], "unclassified")
        validate_batch(batch(replace(flow, counterpart_source_id="counterpart-001",
            counterpart_account=AccountKey("other-provider", "other-account"))), RAW)
        for record in (replace(flow, transfer_reference=None), replace(flow, amount=Money(D(0), "CAD")),
                       replace(flow, status="guessed"), replace(flow, type="buy"),
                       replace(flow, counterpart_source_id="ambiguous-id")):
            with self.assertRaises(ValueError):
                validate_batch(batch(record), RAW)

    def test_crypto_network_legs_pending_fees_and_cancellations(self):
        trade = CryptoTransaction(KEY, AT, "purchase", "completed", (
            CryptoLeg(ACCOUNT, BTC, D("0.00100000")), CryptoLeg(ACCOUNT, CAD, D("-100"))), fees=None)
        for status in ("completed", "pending", "cancelled"):
            validate_batch(batch(replace(trade, status=status)), RAW)
        self.assertIsNone(json.loads(canonical_json(batch(trade)))["records"][0]["fees"])
        known_free = replace(trade, fees=())
        self.assertEqual(json.loads(canonical_json(batch(known_free)))["records"][0]["fees"], [])
        swapped = replace(trade, type="swap", transfer_reference="swap-001", legs=(
            CryptoLeg(ACCOUNT, BTC, D("0.00100000")),
            CryptoLeg(ACCOUNT, replace(BTC, symbol="LBTC", network="liquid"), D("-0.00100000"))))
        validate_batch(batch(swapped), RAW)
        void = replace(trade, key=replace(KEY, revision="2", supersedes_revision="1", change="void"), status="cancelled")
        validate_batch(batch(void), RAW)
        for record in (replace(void, status="completed"), replace(trade, type="observed_balance"),
                       replace(trade, legs=()), replace(trade, fees=(Money(D(-1), "CAD"),))):
            with self.assertRaises(ValueError):
                validate_batch(batch(record), RAW)

    def test_malformed_mutable_contracts_and_extreme_precision_fail(self):
        good = batch(HOLDING)
        for value in (replace(good, records=[HOLDING]), replace(good, coverage=("not coverage",)),
                      replace(good, records=(replace(HOLDING, key="not a key"),)),
                      replace(good, evidence=replace(EVIDENCE, warnings="not a tuple")),
                      replace(good, evidence=replace(EVIDENCE, mappings=(("only one",),)))):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_batch(value, RAW)
        for quantity in (D("0.000000001"), D("1e-100"), D("123456789123456789123456789.000000001")):
            with self.assertRaisesRegex(ValueError, "satoshis"):
                validate_batch(batch(replace(HOLDING, asset=BTC, quantity=quantity)), RAW)
        validate_batch(batch(replace(HOLDING, asset=BTC, quantity=D("0.0010000000"))), RAW)

    def test_protocol_is_pure_contract_not_an_installer(self):
        class SyntheticAdapter:
            info = INFO
            def detect(self, raw):
                return Detection(raw == RAW, "2024-v1" if raw == RAW else None, "synthetic bytes")
            def normalize(self, raw, *, export_version):
                return batch(HOLDING)
        adapter = SyntheticAdapter()
        self.assertIsInstance(adapter, SourceAdapter)
        validate_batch(adapter.normalize(RAW, export_version="2024-v1"), RAW)


if __name__ == "__main__":
    unittest.main()
