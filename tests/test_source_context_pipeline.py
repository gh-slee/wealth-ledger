"""Synthetic v2 child/CLI plans, strict context, drift and receipt rejection."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_source_builtin import CONTEXT, ALIAS, ROOT, fixture
from wealth_ledger.source_builtin import registrations
from wealth_ledger.source_context_pipeline import (BLOCKER, _plan, context_document, contexts_from_document,
    parse_context, parse_sources, plan_context_sources, validate_receipt)
from wealth_ledger.source_environment import digest
from wealth_ledger.source_pipeline import DEFAULT_CONFIG, SourcePlanError
from wealth_ledger.source_registry import build_registry

CONTEXTS = (CONTEXT, replace(CONTEXT, account_alias=ALIAS))
RAW = (fixture("wealthsimple-holdings.csv"), fixture("bull-orders.csv"))


class ContextSchemaTests(unittest.TestCase):
    def pure_plan(self, **kwargs):
        return _plan(RAW, CONTEXTS, DEFAULT_CONFIG, {}, registry=build_registry(builtins=registrations()), environment="a" * 64, **kwargs)

    def test_closed_context_schema_roundtrips_and_rejects_executable_fields(self):
        document = context_document(CONTEXTS)
        self.assertEqual(contexts_from_document(document, 2), CONTEXTS)
        for change in ({"module": "untrusted:factory"}, {"evidence_at": "2024-03-01"},
                       {"source_timezone": "Invalid/Zone"}, {"source_reference": ""}, {"revisions": {}}):
            with self.subTest(change=change), self.assertRaises(SourcePlanError):
                parse_context({**document["inputs"][0], **change})
        with self.assertRaises(SourcePlanError):
            contexts_from_document(document, 1)
        with self.assertRaises(SourcePlanError):
            contexts_from_document({**document, "schema_version": True}, 2)

    def test_pure_plan_is_deterministic_private_summary_and_not_bookable(self):
        first, batches = self.pure_plan()
        self.assertEqual(first, self.pure_plan()[0])
        self.assertEqual(first["booking_blocker"], BLOCKER)
        self.assertFalse(first["ingestible"])
        validate_receipt(first)
        rendered = json.dumps(first)
        for private in (ALIAS, CONTEXT.source_reference, "DEMO-TFSA", "DEMO-BUY-BTC", "source_fields", "quantity"):
            self.assertNotIn(private, rendered)
        self.assertEqual(len(batches), 2)
        self.assertEqual(first["inputs"][1]["record_counts"], {"cash_flows": 1, "crypto_transactions": 2})

    def test_valid_empty_batch_keeps_unknown_coverage_without_zero_asset_inference(self):
        from wealth_ledger.source_builtin import WealthsimpleHoldings
        from wealth_ledger.source_builtin import WS_FORMAT
        from wealth_ledger import source_v2 as v2
        original = WealthsimpleHoldings().normalize(RAW[0], export_version=WS_FORMAT, context=CONTEXT)
        empty = replace(original, records=(), snapshots=(), coverage=())
        v2.validate_batch(empty, RAW[0])
        with patch.object(WealthsimpleHoldings, "normalize", return_value=empty):
            receipt, _ = _plan((RAW[0],), (CONTEXT,), DEFAULT_CONFIG, {}, registry=build_registry(builtins=registrations()), environment="a" * 64)
        validate_receipt(receipt)
        self.assertEqual(receipt["inputs"][0]["record_counts"], {})
        self.assertEqual(receipt["inputs"][0]["coverage_count"], 0)
        self.assertEqual(empty.membership.status, "unknown")
        self.assertFalse(receipt["ingestible"])

    def test_changed_context_changes_fingerprint_even_for_equal_financial_records(self):
        first, _ = self.pure_plan()
        changed = (replace(CONTEXT, source_reference="another-evidence-reference"), CONTEXTS[1])
        second, _ = _plan(RAW, changed, DEFAULT_CONFIG, {}, registry=build_registry(builtins=registrations()), environment="a" * 64)
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])
        self.assertNotEqual(first["contexts_sha256"], second["contexts_sha256"])

    def test_malformed_or_rehashed_receipt_schema_rejected(self):
        original, _ = self.pure_plan()
        for change in ({"ingestible": True}, {"schema_version": True}, {"environment_sha256": "bad"}, {"inputs": []}):
            value = {**original, **change}
            value["fingerprint"] = digest({k: v for k, v in value.items() if k != "fingerprint"})
            with self.assertRaises(SourcePlanError):
                validate_receipt(value)
        malformed = json.loads(json.dumps(original)); malformed["inputs"][0]["record_counts"] = {"holdings": True}
        malformed["fingerprint"] = digest({k:v for k,v in malformed.items() if k != "fingerprint"})
        with self.assertRaises(SourcePlanError):
            validate_receipt(malformed)

    def test_invalid_context_does_not_execute_source_normalizer(self):
        with patch("wealth_ledger.source_builtin.WealthsimpleHoldings.normalize", side_effect=AssertionError("must not normalize")):
            with self.assertRaises(SourcePlanError):
                _plan(RAW, (replace(CONTEXT, source_timezone="Unknown/Zone"), CONTEXTS[1]), DEFAULT_CONFIG, {}, registry=build_registry(builtins=registrations()), environment="a" * 64)


class IsolatedContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-source-context-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = [self.root / "holdings.csv", self.root / "orders.csv"]
        for path, raw in zip(self.paths, RAW):
            path.write_bytes(raw)
        self.config = self.root / "parsers.json"; self.config.write_bytes(DEFAULT_CONFIG)
        self.context = self.root / "context.json"; self.context.write_text(json.dumps(context_document(CONTEXTS)))

    def plan(self, **kwargs):
        return plan_context_sources(self.paths, contexts=CONTEXTS, config_path=self.config, **kwargs)

    def test_actual_fresh_child_returns_strict_batches_and_revalidates_receipt(self):
        parsed = parse_sources(self.paths, contexts=CONTEXTS, config_path=self.config)
        self.assertEqual(parsed.raw, RAW)
        self.assertEqual(len(parsed.batches), 2)
        self.assertEqual(parsed.batches[0].evidence.context, CONTEXT)
        repeated = self.plan(previous=parsed.receipt, expected_environment=parsed.receipt["environment_sha256"])
        self.assertEqual(repeated, parsed.receipt)
        self.assertFalse(list(self.root.rglob("*.sqlite3")))
        changed = list(CONTEXTS); changed[1] = replace(changed[1], account_alias="different-source")
        with self.assertRaises(SourcePlanError) as caught:
            plan_context_sources(self.paths, contexts=tuple(changed), config_path=self.config, previous=parsed.receipt)
        self.assertEqual(caught.exception.code, "stale_plan")

    def test_actual_cli_uses_same_context_contract_and_revalidation(self):
        command = [sys.executable, "-B", "-m", "wealth_ledger.source_cli", *map(str, self.paths),
            "--config", str(self.config), "--context", str(self.context)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan, self.plan())
        receipt = self.root / "receipt.json"; receipt.write_text(json.dumps(plan))
        verify = subprocess.run(command + ["--verify", str(receipt)], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        self.assertEqual(json.loads(verify.stdout), plan)
        self.assertFalse(list(self.root.rglob("*.sqlite3")))

    def test_environment_mismatch_blocks_actual_child(self):
        with self.assertRaises(SourcePlanError) as caught:
            self.plan(expected_environment="0" * 64)
        self.assertEqual(caught.exception.code, "stale_environment")

    def test_timeout_and_unknown_context_are_redacted(self):
        with patch("wealth_ledger.source_context_pipeline.subprocess.run", side_effect=subprocess.TimeoutExpired("synthetic", 1)):
            with self.assertRaises(SourcePlanError) as caught:
                self.plan(timeout=1)
        self.assertEqual(caught.exception.code, "parser_timeout")
        with self.assertRaises(SourcePlanError):
            plan_context_sources(self.paths, contexts=(CONTEXT,), config_path=self.config)

    def test_after_child_input_changes_reject_before_returning_results(self):
        real_run = subprocess.run
        def mutate(*args, **kwargs):
            result = real_run(*args, **kwargs)
            self.paths[0].write_bytes(RAW[0] + b"\n")
            return result
        with patch("wealth_ledger.source_context_pipeline.subprocess.run", side_effect=mutate):
            with self.assertRaises(SourcePlanError) as caught:
                self.plan()
        self.assertEqual(caught.exception.code, "stale_plan")
