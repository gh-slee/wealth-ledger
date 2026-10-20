"""Source-aware append-only declarations, using synthetic isolated ledgers only."""
from dataclasses import replace
from decimal import Decimal as D, localcontext
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_source_legacy_projection as fixtures
from test_source_projection import hashes
from wealth_ledger import wallet
from wealth_ledger.application import ApplicationService
from wealth_ledger.crypto_opening import import_opening, latest_opening
from wealth_ledger.source_legacy_projection import project_compatible_sources
from wealth_ledger.wallet_basis import has_canonical_sources
from wealth_ledger.workspace import resolve_workspace

AT = fixtures.AT
START = fixtures.START
NOW = "2024-03-02T00:00:00Z"


class SourceWalletDeclarationTests(unittest.TestCase):
    setUp = fixtures.LegacyProjectionTests.setUp
    native = fixtures.LegacyProjectionTests.native
    ws = fixtures.LegacyProjectionTests.ws
    bull = fixtures.LegacyProjectionTests.bull
    commit = fixtures.LegacyProjectionTests.commit
    new_purchase = fixtures.LegacyProjectionTests.new_purchase

    def model(self, at=AT):
        return project_compatible_sources(self.root, as_of=at, period_start=START)

    def opening(self, total="0.008", **changes):
        path = self.base/"opening.json"
        value = {"reported_total_btc_equivalent": total, "reference_as_of": "2024-02-01T00:00:00Z",
                 "declared_on": "2024-03-01", "balance_scope": "all_wallets_btc_plus_lbtc",
                 "basis": "Synthetic pre-source holding declaration", "confirmed_by": "synthetic-example", **changes}
        path.write_text(json.dumps(value)+"\n")
        return import_opening(self.root, path)

    def balance(self, total="0.008", at=AT):
        return wallet.add_balance(self.root, total, at, now=NOW)

    def fee(self, balance=None, when="2024-02-20T00:00:00Z", reference="synthetic-fee"):
        return wallet.add_event(self.root, type="fee", quantity_btc="0.0001", occurred_at=when,
                                source="Synthetic wallet", reference=reference, balance_id=balance, now=NOW)

    def test_empty_and_native_declarations_keep_the_original_contract(self):
        self.assertFalse(has_canonical_sources(self.root))
        self.assertEqual(hashes(self.root), {})
        empty = self.balance()
        self.assertIsNone(empty["recorded_expected_btc"])
        self.assertNotIn("calculation_basis", empty)
        self.assertTrue(empty["unknown_prior_history"])

    def test_mixed_duplicate_buys_are_counted_once_in_recorded_expectation(self):
        self.native(); self.commit(self.bull())
        record = self.balance()
        self.assertEqual(D(record["recorded_expected_btc"]), D("0.007"))
        self.assertEqual(record["recorded_residual_btc"], "0.00100000")
        self.assertFalse(record["unknown_prior_history"])
        self.assertEqual(len(record["calculation_basis"]["projection_sha256"]),64)
        detail = wallet.balance_detail(self.root, record["record_id"])
        self.assertEqual(detail["reconciliation"]["recorded_expected_btc"], record["recorded_expected_btc"])
        self.assertFalse((self.root/"reports/latest.json").exists())

    def test_canonical_unknown_start_never_becomes_a_zero_expected_balance(self):
        self.commit(self.bull())
        record = self.balance()
        self.assertIsNone(record["recorded_expected_btc"])
        self.assertIsNone(record["recorded_residual_btc"])
        self.assertTrue(record["unknown_prior_history"])
        self.assertEqual(self.model()["btc"]["quantity_btc"], "0.00800000")

    def test_later_canonical_purchase_is_applied_after_anchor_only(self):
        self.commit(self.bull()); self.balance("0.010", "2024-02-01T00:00:00Z")
        self.commit(self.new_purchase())
        record = self.balance("0.0109")
        self.assertEqual(record["recorded_expected_btc"], "0.01100000")
        self.assertEqual(record["recorded_residual_btc"], "-0.00010000")

    def test_linked_fee_recalculates_gap_without_changing_recorded_expectation(self):
        self.native(); self.commit(self.bull()); self.balance("0.008", "2024-02-01T00:00:00Z")
        self.commit(self.new_purchase()); record = self.balance("0.0089")
        event = self.fee(record["record_id"])
        detail = wallet.balance_detail(self.root, record["record_id"])["reconciliation"]
        self.assertEqual(detail["recorded_residual_btc"], "-0.00010000")
        self.assertEqual(detail["residual_btc"], "0.00000000")
        self.assertEqual(detail["status"], "arithmetic_match")
        self.assertIn(event["record_id"], detail["linked_event_ids"])
        revised = wallet.revise(self.root, event["record_id"], expected_revision=1, reason="Synthetic correction",
                                 quantity_btc="0.00005")
        self.assertEqual(revised["revision"],2)
        self.assertEqual(wallet.balance_detail(self.root, record["record_id"])["reconciliation"]["residual_btc"], "-0.00005000")

    def test_first_interval_uses_canonical_history_boundary(self):
        self.commit(self.bull()); record = self.balance()
        before = hashes(self.root)
        with self.assertRaisesRegex(ValueError,"outside balance"):
            self.fee(record["record_id"], "2023-01-01T00:00:00Z")
        self.assertEqual(hashes(self.root),before)

    def test_corrupted_canonical_archive_blocks_new_balance_without_writes(self):
        self.commit(self.bull())
        target = next((self.root/"data/raw/source-v2").glob("*.csv")); target.chmod(0o600);target.write_bytes(b"invalid")
        before = hashes(self.root)
        with self.assertRaises(ValueError): self.balance()
        self.assertEqual(hashes(self.root),before)

    def test_native_crypto_report_view_stays_gated_for_canonical_workspaces(self):
        self.commit(self.bull())
        before=hashes(self.root)
        with self.assertRaisesRegex(ValueError,"report_projection_unavailable"):
            wallet.make_crypto_view(self.root, AT, strict=False)
        self.assertEqual(hashes(self.root),before)

    def test_canonical_opening_uses_all_net_purchases_and_preserves_unknown_costs(self):
        self.commit(self.bull()); opening = self.opening()
        self.assertEqual(opening["opening_btc_equivalent_qty"],"0.00100000")
        self.assertEqual(opening["reference_purchased_btc_equivalent"],"0.00700000")
        self.assertEqual(len(opening["reference_purchases"]),2)
        self.assertEqual(opening["source_account"],"all-wallets-btc-plus-lbtc")
        self.assertIsNone(opening["cost_cad"]); self.assertIsNone(opening["historical_contribution_cad"])
        result=self.model(); self.assertEqual(result["btc"]["quantity_btc"],"0.00800000")
        self.assertEqual(result["btc"]["opening"]["id"],opening["id"])
        record=self.balance(); self.assertEqual(record["recorded_expected_btc"],"0.00800000")
        self.assertFalse(record["unknown_prior_history"])

    def test_known_fee_is_frozen_into_opening_arithmetic_without_becoming_a_purchase(self):
        self.commit(self.bull()); self.fee(when="2024-01-31T23:00:00Z")
        opening=self.opening("0.0079")
        self.assertEqual(opening["opening_btc_equivalent_qty"],"0.00100000")
        self.assertEqual(opening["reference_known_event_btc"],"-0.00010000")
        self.assertEqual(self.model()["btc"]["quantity_btc"],"0.00790000")
        self.assertFalse(self.model()["wallet"]["opening_overlap"])

    def test_opening_duplicate_and_later_buy_never_rederive_the_prior_quantity(self):
        self.commit(self.bull()); first=self.opening(); self.commit(self.new_purchase())
        duplicate=self.opening()
        self.assertEqual(duplicate["status"],"duplicate"); self.assertEqual(first["id"],duplicate["id"])
        self.assertEqual(self.model()["btc"]["quantity_btc"],"0.00900000")
        self.assertFalse(self.model()["wallet"]["opening_overlap"])

    def test_old_date_purchase_backfill_conflicts_with_frozen_opening_until_observed(self):
        self.commit(self.bull()); self.opening()
        self.commit(self.new_purchase(when="2024-01-31T23:01:00Z"))
        result=self.model(); self.assertTrue(result["wallet"]["opening_overlap"])
        self.assertIsNone(result["btc"]["quantity_btc"])
        record=self.balance("0.0085")
        self.assertIsNone(record["recorded_expected_btc"])
        self.assertEqual(self.model()["btc"]["quantity_btc"],"0.00850000")
        self.assertTrue(self.model()["wallet"]["opening_overlap"])

    def test_backfilled_or_revised_reference_fee_marks_opening_overlap(self):
        self.commit(self.bull()); self.opening(); self.fee(when="2024-01-31T23:00:00Z")
        self.assertTrue(self.model()["wallet"]["opening_overlap"])
        self.assertEqual(latest_opening(self.root)["opening_btc_equivalent_qty"],"0.00100000")

    def test_link_only_fee_revision_does_not_change_opening_footprint(self):
        self.commit(self.bull()); event=self.fee(when="2024-01-31T23:00:00Z"); self.opening("0.0079")
        balance=self.balance("0.0079", "2024-02-01T00:00:00Z")
        wallet.revise(self.root, event["record_id"], expected_revision=1, reason="Synthetic attribution", action="link", balance_id=balance["record_id"])
        self.assertFalse(self.model()["wallet"]["opening_overlap"])

    def test_explicit_opening_revision_preserves_one_all_wallet_scope(self):
        self.native(); self.opening(); self.commit(self.bull())
        revised=self.opening("0.0085",basis="Explicit synthetic correction")
        self.assertEqual(revised["revision"],2)
        self.assertEqual(revised["source_account"],fixtures.ALIAS)
        self.assertEqual(latest_opening(self.root)["id"],revised["id"])
        self.assertEqual(self.model()["btc"]["quantity_btc"],"0.00850000")
        before=hashes(self.root)
        with self.assertRaises(ValueError):
            import_opening(self.root,self.base/"opening.json",source_account="other-synthetic-scope")
        self.assertEqual(hashes(self.root),before)

    def test_small_process_decimal_context_does_not_round_opening_or_residual(self):
        self.commit(self.bull())
        with localcontext() as context:
            context.prec=4; context.rounding="ROUND_DOWN"
            opening=self.opening("0.00812345"); record=self.balance("0.00812346")
        self.assertEqual(opening["opening_btc_equivalent_qty"],"0.00112345")
        self.assertEqual(record["recorded_expected_btc"],"0.00812345")
        self.assertEqual(record["recorded_residual_btc"],"0.00000001")

    def test_negative_opening_and_holdings_only_source_are_rejected_without_mutation(self):
        self.commit(self.ws()); before=hashes(self.root)
        with self.assertRaises(ValueError): self.opening()
        self.assertEqual(hashes(self.root),before)
        self.commit(self.bull()); before=hashes(self.root)
        with self.assertRaises(ValueError): self.opening("0.001")
        self.assertEqual(hashes(self.root),before)

    def test_pre_source_events_cannot_be_hidden_in_a_derived_opening(self):
        self.commit(self.bull()); self.fee(when="2023-01-01T00:00:00Z")
        before=hashes(self.root)
        with self.assertRaisesRegex(ValueError,"Pre-source events"): self.opening()
        self.assertEqual(hashes(self.root),before)

    def test_zero_opening_and_zero_reported_balance_remain_valid_values(self):
        self.commit(self.bull()); self.opening("0.007")
        record=self.balance("0")
        self.assertEqual(record["recorded_residual_btc"],"-0.00700000")
        self.assertEqual(D(self.model()["btc"]["quantity_btc"]),D(0))

    def test_third_provider_purchase_contributes_without_new_provider_dispatch(self):
        from test_source_v2 import batch, purchase, RAW, META
        event=purchase()
        value=batch((event,),accounts=(replace(META,role="crypto",account_type="crypto"),))
        self.commit((value,RAW))
        opening=self.opening("0.0015")
        self.assertEqual(opening["opening_btc_equivalent_qty"],"0.00050000")
        record=self.balance("0.0014")
        self.assertEqual(record["recorded_expected_btc"],"0.00150000")
        self.assertEqual(record["recorded_residual_btc"],"-0.00010000")

    def test_service_record_recovery_does_not_duplicate_canonical_based_balance(self):
        self.commit(self.bull()); self.opening()
        service=ApplicationService(resolve_workspace(explicit=self.root)); request={"type":"synthetic-balance"}
        def action(stage): return wallet.add_balance(stage,"0.008",AT,now=NOW)
        first=service.record(request,action,label="synthetic-wallet",operation_id="OP-0123456789abcdef")
        second=service.record(request,lambda _: self.fail("Recovery must not rerun declaration"),label="synthetic-wallet",operation_id="OP-0123456789abcdef")
        self.assertEqual(first["record_id"],second["record_id"])
        self.assertEqual(len(wallet.records(self.root,"balance")),1)
        self.assertEqual(len(service.operations()),2)

    def test_cli_append_and_show_share_the_canonical_basis(self):
        self.commit(self.bull()); self.opening()
        command="from pathlib import Path; from wealth_ledger.wallet_cli import run; run(Path.cwd(), 'balance')"
        def run(*args):
            result=subprocess.run([sys.executable,"-c",command,"--workspace",str(self.root),"--locale","en-CA",*args],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            return json.loads(result.stdout)
        result=run("add","--quantity-btc","0.0079","--as-of",AT)
        self.assertEqual(result["recorded_residual_btc"],"-0.00010000")
        detail=run("show",result["record_id"])
        self.assertEqual(detail["reconciliation"]["expected_btc"],"0.00800000")

    def test_opening_reference_footprint_remains_valid_before_the_reference_cutoff(self):
        self.commit(self.bull()); self.opening()
        model=self.model("2024-01-02T18:00:00Z")
        self.assertEqual(model["btc"]["quantity_btc"],"0.00500000")
        self.assertFalse(model["wallet"]["opening_overlap"])

    def test_duplicate_balance_preserves_first_recorded_basis_after_source_backfill(self):
        self.commit(self.bull()); first=self.balance()
        self.commit(self.new_purchase())
        duplicate=self.balance()
        self.assertEqual(duplicate["status"],"duplicate")
        self.assertEqual(duplicate["calculation_basis"],first["calculation_basis"])
        self.assertEqual(len(wallet.records(self.root,"balance")),1)
        self.assertIsNone(duplicate["recorded_expected_btc"])

    def test_corrupt_opening_evidence_blocks_balance_event_and_revision(self):
        self.commit(self.bull()); opening=self.opening(); balance=self.balance()
        path=self.root/latest_opening(self.root)["source_path"];path.chmod(0o600);path.write_bytes(b"invalid")
        before=hashes(self.root)
        for action in (lambda:self.balance("0.0081","2024-03-01T01:00:00Z"),lambda:self.fee(),
                       lambda:wallet.revise(self.root,balance["record_id"],expected_revision=1,reason="Synthetic correction",quantity_btc="0.0081")):
            with self.assertRaises(ValueError): action()
        self.assertEqual(hashes(self.root),before)
