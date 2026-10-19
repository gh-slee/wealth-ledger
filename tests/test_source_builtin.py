"""Synthetic parser parity, explicit context and canonical booking boundary tests."""
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, localcontext
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wealth_ledger import source_v2 as v2
from wealth_ledger.source_builtin import BULL_FORMAT, WS_FORMAT, BullBitcoinOrders, WealthsimpleHoldings, registrations
from wealth_ledger.source_formats import parse_bull, parse_wealthsimple
from wealth_ledger.source_registry import build_registry

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = v2.ParseContext(datetime.fromisoformat("2024-03-01T12:00:00+00:00"), "synthetic-fixture")
ALIAS = "synthetic-bull"


def fixture(name):
    return (ROOT / "examples/data" / name).read_bytes()


def csv_change(raw, changes):
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    for row_index, column, value in changes:
        rows[row_index][rows[0].index(column)] = value
    target = io.StringIO(newline="")
    csv.writer(target).writerows(rows)
    return target.getvalue().encode()


class BuiltinParserTests(unittest.TestCase):
    def ws(self, raw=None, context=CONTEXT):
        raw = fixture("wealthsimple-holdings.csv") if raw is None else raw
        return WealthsimpleHoldings().normalize(raw, export_version=WS_FORMAT, context=context)

    def bull(self, raw=None, context=None):
        raw = fixture("bull-orders.csv") if raw is None else raw
        context = context or replace(CONTEXT, account_alias=ALIAS)
        return BullBitcoinOrders().normalize(raw, export_version=BULL_FORMAT, context=context)

    def test_registry_detects_two_explicit_builtins_without_changing_empty_default(self):
        registry = build_registry(builtins=registrations())
        self.assertEqual(registry.detect(fixture("wealthsimple-holdings.csv")).descriptor.info.adapter_id, "wealthsimple.holdings")
        self.assertEqual(registry.detect(fixture("bull-orders.csv")).descriptor.info.adapter_id, "bullbitcoin.orders")
        self.assertEqual(build_registry().adapters, ())
        for adapter in (WealthsimpleHoldings(), BullBitcoinOrders()):
            self.assertFalse(adapter.detect(b"bad\xff").matched)
            self.assertFalse(adapter.detect(bytearray(b"mutable")).matched)

    def test_holdings_parity_preserves_every_financial_field_and_legacy_ids(self):
        raw = fixture("wealthsimple-holdings.csv")
        _, at, rows, accounts, _ = parse_wealthsimple(raw)
        batch = self.ws(raw)
        by_id = {(r.key.account.account_id, r.key.source_id): r for r in batch.records}
        for old in rows:
            new = by_id[(old["account_id"], old["security_id"])]
            self.assertEqual(new.as_of, at)
            self.assertEqual(new.name, old["name"])
            self.assertEqual(new.instrument_type, old["security_type"])
            self.assertEqual(new.exchange, old["exchange"])
            self.assertEqual((new.quantity, new.unit_price.amount, new.market_value.amount, new.cost_native.amount,
                new.cost_cad.amount, new.unrealized.amount), tuple(old[k] for k in
                    ("quantity", "price", "market_native", "book_native", "book_cad", "unrealized_native")))
        self.assertEqual({a.key.account_id for a in batch.accounts}, set(accounts))
        self.assertTrue(all(a.masked_identifier.startswith("****") for a in batch.accounts))
        self.assertEqual(batch.membership.status, "unknown")
        self.assertEqual({c.status for c in batch.coverage}, {"partial"})
        self.assertEqual(v2.decode_batch(v2.canonical_json(batch).encode(), raw), batch)

    def test_holdings_semantic_identity_matches_original_ledger_hash(self):
        from wealth_ledger.core import _holdings_plan
        raw = fixture("wealthsimple-holdings.csv")
        plan = _holdings_plan(None, parse_wealthsimple(raw), "monthly")
        self.assertEqual(dict(self.ws(raw).evidence.mappings)["legacy_semantic_hash"], plan["semantic_hash"])

    def test_row_order_numeric_spelling_and_context_do_not_change_holdings_identity(self):
        raw = fixture("wealthsimple-holdings.csv")
        changed = csv_change(raw, [(1, "Quantity", "10.0000")])
        rows = list(csv.reader(io.StringIO(changed.decode())))
        target = io.StringIO(newline=""); csv.writer(target).writerows([rows[0], *reversed(rows[1:-1]), rows[-1]])
        a, b = self.ws(raw), self.ws(target.getvalue().encode(), replace(CONTEXT, source_reference="renamed-source"))
        self.assertEqual(a.records, b.records)
        self.assertEqual([v2.canonical_json(r) for r in a.records], [v2.canonical_json(r) for r in b.records])
        self.assertEqual(a.snapshots, b.snapshots)
        self.assertNotEqual(a.evidence.raw_sha256, b.evidence.raw_sha256)

    def test_explicit_position_scope_parents_are_preserved_not_guessed(self):
        original = self.ws()
        raw = csv_change(fixture("wealthsimple-holdings.csv"), [(1, "Market Value", "201")])
        revised = self.ws(raw)
        self.assertIsNone(revised.records[0].key.supersedes_revision)
        contexts = tuple(v2.RevisionContext(r.key.account, r.kind, r.key.source_id, r.observation_id, r.key.revision) for r in original.records)
        snapshot = original.snapshots[0]
        scopes = (v2.ScopeRevisionContext("snapshot", snapshot.source_id, snapshot.revision), *(
            v2.ScopeRevisionContext("coverage", c.scope_id, c.revision, c.account, c.kind, c.observation_id) for c in original.coverage))
        corrected = self.ws(raw, replace(CONTEXT, revisions=contexts, scope_revisions=scopes))
        self.assertTrue(all(r.key.change == "correction" and r.revision_reason for r in corrected.records))
        self.assertEqual(corrected.snapshots[0].supersedes_revision, snapshot.revision)

    def test_unused_parent_and_wrong_format_are_rejected(self):
        parent = v2.RevisionContext(v2.AccountKey("wealthsimple", "absent"), "holdings", "missing", "missing", "old")
        with self.assertRaises(ValueError):
            self.ws(context=replace(CONTEXT, revisions=(parent,)))
        with self.assertRaises(ValueError):
            self.ws(context=replace(CONTEXT, format_selection=BULL_FORMAT))
        with self.assertRaises(ValueError):
            self.ws(context=replace(CONTEXT, account_alias="replace-source-account"))

    def test_source_values_and_diagnostics_retained_without_repair(self):
        raw = csv_change(fixture("wealthsimple-holdings.csv"), [(1, "Market Value", "999"), (1, "Book Value (CAD)", "0")])
        batch = self.ws(raw)
        position = next(r for r in batch.records if r.market_value.amount == Decimal("999"))
        self.assertEqual(position.cost_cad.amount, 0)
        self.assertIn("market_math", [d.code for d in batch.evidence.diagnostics])
        self.assertIn("unrealized_math", [d.code for d in batch.evidence.diagnostics])
        self.assertEqual(position.unit_price.amount, Decimal("20"))

    def test_bull_requires_explicit_alias_and_retains_legacy_order_identity(self):
        with self.assertRaises(ValueError):
            self.bull(context=CONTEXT)
        raw = fixture("bull-orders.csv")
        _, old, _, _, semantic = parse_bull(raw, ALIAS)
        batch = self.bull(raw)
        self.assertEqual({r.key.source_id for r in batch.records}, {r["order_key"] for r in old})
        self.assertEqual(dict(batch.evidence.mappings)["legacy_semantic_hash"], semantic)
        self.assertEqual({r.key.account.account_id for r in batch.records if r.kind == "crypto_transactions"}, {ALIAS})
        self.assertEqual({a.role for a in batch.accounts}, {"crypto", "funding"})
        self.assertEqual(v2.decode_batch(v2.canonical_json(batch).encode(), raw), batch)

    def test_bull_funding_and_purchase_legs_are_not_two_contributions(self):
        batch = self.bull()
        funding = [r for r in batch.records if r.kind == "cash_flows"]
        buys = [r for r in batch.records if r.kind == "crypto_transactions"]
        self.assertTrue(all(r.type == "deposit" and r.direction == "in" and r.boundary == "unclassified" for r in funding))
        self.assertTrue(all(r.fees is None and len(r.legs) == 2 for r in buys))
        self.assertEqual({r.legs[1].asset.network for r in buys}, {"bitcoin", "liquid"})
        self.assertTrue(all(r.legs[0].quantity == r.acquisition_cost.amount.copy_negate() for r in buys))
        self.assertTrue(all(r.lifecycle.completed_at == r.occurred_at for r in batch.records))
        self.assertTrue(all(r.acquisition_cost == r.acquisition_cost_cad for r in buys))
        self.assertEqual(batch.membership.status, "unknown")
        self.assertEqual({c.status for c in batch.coverage}, {"partial"})

    def test_bull_unknown_rate_unit_preserves_audit_values_without_fabrication(self):
        batch = self.bull()
        funding = next(r for r in batch.records if r.kind == "cash_flows")
        self.assertIsNone(funding.lifecycle.index_rate)
        self.assertEqual(dict(funding.source_fields)["index_rate_amount"], "100000")
        self.assertEqual(dict(funding.source_fields)["index_rate_currency"], "")

    def test_bull_reordered_cumulative_rows_keep_revision_keys(self):
        raw = fixture("bull-orders.csv")
        rows = list(csv.reader(io.StringIO(raw.decode())))
        output = io.StringIO(newline=""); csv.writer(output).writerows([rows[0], *reversed(rows[1:]), rows[1]])
        a, b = self.bull(raw), self.bull(output.getvalue().encode())
        self.assertEqual(a.records, b.records)
        self.assertEqual(a.coverage, b.coverage)
        self.assertEqual(dict(b.evidence.diagnostics[-1].parameters)["duplicates"], "1")

    def test_bull_pending_completion_needs_explicit_parent_and_keeps_lifecycle(self):
        raw = fixture("bull-orders.csv")
        pending = csv_change(raw, [(2, "ORDER_STATUS", "Pending"), (2, "PAYIN_STATUS", "Pending"),
            (2, "PAYOUT_STATUS", "Pending"), (2, "COMPLETED_AT (UTC)", ""), (2, "SENT_AT (UTC)", "")])
        old = next(r for r in self.bull(pending).records if r.status == "pending")
        context = replace(CONTEXT, account_alias=ALIAS, revisions=(v2.RevisionContext(old.key.account, old.kind,
            old.key.source_id, "", old.key.revision),))
        new = next(r for r in self.bull(raw, context).records if r.key.source_id == old.key.source_id)
        self.assertEqual((new.status, new.key.change, new.key.supersedes_revision), ("completed", "correction", old.key.revision))
        self.assertNotEqual(new.occurred_at, old.occurred_at)

    def test_unsupported_bull_status_type_network_and_satoshi_rejected(self):
        for column, value in [("ORDER_TYPE", "Sell Bitcoin"), ("PAYOUT_METHOD", "Unsupported network"),
                               ("PAYOUT_AMOUNT", "0.000000001"), ("ORDER_STATUS", "Unknown status")]:
            with self.subTest(column=column), self.assertRaises(ValueError):
                self.bull(csv_change(fixture("bull-orders.csv"), [(2, column, value)]))

    def test_pure_normalization_never_uses_file_clock_network_database_or_subprocess(self):
        raw_ws, raw_bull = fixture("wealthsimple-holdings.csv"), fixture("bull-orders.csv")
        # Import optional standard modules before denying their mutation interfaces.
        import socket, sqlite3, subprocess
        with patch("builtins.open", side_effect=AssertionError("file IO")), patch.object(Path, "read_bytes", side_effect=AssertionError("file IO")), \
             patch.object(socket, "socket", side_effect=AssertionError("network")), patch.object(sqlite3, "connect", side_effect=AssertionError("database")), \
             patch.object(subprocess, "run", side_effect=AssertionError("process")):
            first = self.ws(raw_ws), self.bull(raw_bull)
            second = self.ws(raw_ws), self.bull(raw_bull)
        self.assertEqual(first, second)

    def test_decimal_context_does_not_change_pure_outputs(self):
        first = self.ws(), self.bull()
        with localcontext() as context:
            context.prec = 6
            second = self.ws(), self.bull()
        self.assertEqual(first, second)

    def test_builtin_canonical_effects_can_be_verified_without_report_projection(self):
        from wealth_ledger.source_ingestion import SourceInput, prepare_ingestion, commit_ingestion, read_facts, verify_store, new_binding
        from wealth_ledger.workspace import resolve_workspace
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = tuple(SourceInput(batch, fixture(name)) for batch, name in
                [(self.ws(), "wealthsimple-holdings.csv"), (self.bull(), "bull-orders.csv")])
            with patch("wealth_ledger.source_ingestion.environment_fingerprint", return_value="a" * 64):
                plan = prepare_ingestion(root, inputs, bindings=tuple(new_binding(a.key) for item in inputs for a in item.batch.accounts))
                result = commit_ingestion(resolve_workspace(explicit=root), plan)
            facts = read_facts(root)
            self.assertFalse(result["report_projection_ready"])
            self.assertFalse(facts["contributions_calculated"])
            verify_store(root)

    def test_existing_ledger_bindings_preserve_legacy_rows_and_ids(self):
        import sqlite3
        from wealth_ledger.core import import_holdings
        from wealth_ledger.crypto import import_bull_orders, _account_id
        from wealth_ledger.source_ingestion import Binding, SourceInput, new_binding, prepare_ingestion, commit_ingestion, verify_store
        from wealth_ledger.workspace import resolve_workspace
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ws, bull = root / "holdings.csv", root / "orders.csv"
            ws.write_bytes(fixture("wealthsimple-holdings.csv")); bull.write_bytes(fixture("bull-orders.csv"))
            old_snapshot = import_holdings(root, ws, "baseline", json.loads(fixture("fx.json")))
            assumptions = {"btc":"0", "lbtc":"0", "cad":"0", "basis":"Synthetic explicit assumption", "confirmed_by":"synthetic-test"}
            old_crypto = import_bull_orders(root, bull, source_account=ALIAS, opening_assumption=assumptions)
            def rows():
                with sqlite3.connect(root / "data/db/portfolio.sqlite3") as conn:
                    return {table:conn.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()
                        for table in ("accounts", "snapshots", "positions", "sources", "crypto_accounts", "crypto_sources", "crypto_order_revisions")}
            before = rows()
            batches = (self.ws(), self.bull())
            bindings = tuple(Binding(a.key, a.key.account_id, "legacy_holdings") for a in batches[0].accounts) + tuple(
                Binding(a.key, _account_id(ALIAS), "legacy_crypto") if a.role == "crypto" else new_binding(a.key)
                for a in batches[1].accounts)
            with patch("wealth_ledger.source_ingestion.environment_fingerprint", return_value="a" * 64):
                plan = prepare_ingestion(root, tuple(SourceInput(batch, raw) for batch, raw in zip(batches, (ws.read_bytes(), bull.read_bytes()))), bindings=bindings)
                commit_ingestion(resolve_workspace(explicit=root), plan)
            verify_store(root)
            self.assertEqual(rows(), before)
            self.assertEqual(old_snapshot["snapshot_id"], 1)
            self.assertEqual(old_crypto["account_id"], _account_id(ALIAS))

    def test_cross_account_purchase_requires_declared_funding_role(self):
        from wealth_ledger.source_ingestion import IngestionError, SourceInput, new_binding, prepare_ingestion
        original = self.bull()
        changed = replace(original, accounts=tuple(replace(a, role="investment") if a.role == "funding" else a for a in original.accounts))
        with tempfile.TemporaryDirectory() as directory, patch("wealth_ledger.source_ingestion.environment_fingerprint", return_value="a" * 64):
            with self.assertRaises(IngestionError) as caught:
                prepare_ingestion(Path(directory), (SourceInput(changed, fixture("bull-orders.csv")),), bindings=tuple(new_binding(a.key) for a in changed.accounts))
            self.assertEqual(caught.exception.code, "unsupported_effect")
            self.assertFalse(list(Path(directory).rglob("*.sqlite3")))
