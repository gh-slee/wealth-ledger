"""Synthetic canonical-store backup/restore and strict source-evidence acceptance."""
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import test_web as foundation
from test_source_v2 import RAW, ACCOUNT, batch, funding, purchase
from wealth_ledger import source_ingestion as ingestion
from wealth_ledger.workspace import resolve_workspace


@unittest.skipUnless(foundation.AVAILABLE,"Optional Web dependencies are not installed")
class CanonicalBackupTests(unittest.TestCase):
    setUp=foundation.WebTests.setUp
    bootstrap=foundation.WebTests.bootstrap
    login=foundation.WebTests.login
    mutate=foundation.WebTests.mutate
    portfolio=foundation.WebTests.portfolio

    def seed(self):
        self.login(); self.pid=self.portfolio()
        _,self.project=self.store.portfolio(self.pid)
        with patch("wealth_ledger.source_ingestion.environment_fingerprint",return_value="a"*64):
            plan=ingestion.prepare_ingestion(self.project,(ingestion.SourceInput(batch((funding(),purchase())),RAW),),bindings=(ingestion.new_binding(ACCOUNT),))
            ingestion.commit_ingestion(resolve_workspace(explicit=self.project),plan)

    def freeze_valuation(self):
        from wealth_ledger.application import ApplicationService
        from wealth_ledger.source_valuation import read_source_valuation
        inputs={"as_of":"2024-03-01T00:00:00Z","period_start":"2023-12-31T00:00:00Z","generated_at":"2024-03-01T00:00:00Z",
            "fx":{"usd_cad":"1.5","usd_twd":"30","usd_cad_date":"2024-01-30","usd_twd_date":"2024-01-30","usd_cad_source":"synthetic-fixed","usd_twd_source":"synthetic-fixed"}}
        result=ApplicationService(resolve_workspace(explicit=self.project)).source_valuation(inputs)
        return read_source_valuation(self.project,result["observation_id"])

    def test_full_backup_and_fresh_instance_restore_preserve_canonical_facts(self):
        from wealth_ledger.web.backups import backup_instance,restore_instance,database_info
        from wealth_ledger.web.config import WebSettings
        from wealth_ledger.web.storage import Store
        self.seed()
        valuation=self.freeze_valuation()
        facts=ingestion.read_facts(self.project)
        before=database_info(self.project/"data/db/portfolio.sqlite3")
        archive=self.root.parent/"canonical-backup.zip"
        target=WebSettings(self.root.parent/"empty-canonical-restore")
        backup_instance(self.settings,archive)
        with patch("wealth_ledger.source_registry.build_registry",side_effect=AssertionError("Restore must not execute a parser")):
            restore_instance(target,archive)
        _,restored=Store(target).portfolio(self.pid)
        self.assertEqual(ingestion.read_facts(restored),facts)
        from wealth_ledger.source_valuation import read_source_valuation
        self.assertEqual(read_source_valuation(restored,1),valuation)
        self.assertEqual(database_info(restored/"data/db/portfolio.sqlite3"),before)
        self.assertFalse((restored/"reports").exists())
        self.assertEqual(ingestion.verify_store(restored)["schema_version"],1)

    def test_backup_and_adoption_reject_tampered_canonical_evidence(self):
        from wealth_ledger.web.backups import backup_instance
        from wealth_ledger.web.adoption import verify_portfolio
        self.seed()
        with sqlite3.connect(self.project/"data/db/portfolio.sqlite3") as conn:
            relative=conn.execute("SELECT canonical_path FROM src_batches LIMIT 1").fetchone()[0]
        path=self.project/relative;path.chmod(0o600);path.write_bytes(b'{"synthetic":"changed evidence"}')
        with self.assertRaises(ValueError):backup_instance(self.settings,self.root.parent/"rejected.zip")
        with self.assertRaises(ValueError):verify_portfolio(self.project)

    def test_backup_and_adoption_reject_tampered_derived_valuation(self):
        from wealth_ledger.web.backups import backup_instance
        from wealth_ledger.web.adoption import verify_portfolio
        self.seed();self.freeze_valuation()
        path=next((self.project/"data/raw/source-valuations").glob("*.json"))
        path.chmod(0o600);path.write_bytes(b'{"synthetic":"changed derived evidence"}')
        with self.assertRaisesRegex(ValueError,"source_valuation_integrity"):
            backup_instance(self.settings,self.root.parent/"rejected-valuation.zip")
        with self.assertRaisesRegex(ValueError,"source_valuation_integrity"):
            verify_portfolio(self.project)
