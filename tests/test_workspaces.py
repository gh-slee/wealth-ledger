"""Synthetic acceptance for external workspaces, shared services and resource isolation."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from wealth_ledger.application import ApplicationService
from wealth_ledger.core import import_holdings, make_payload
from wealth_ledger.lookthrough import attach_analysis, portfolio_signature
from wealth_ledger.operations import fingerprint
from wealth_ledger.publishing import database_backup
from wealth_ledger.resources import company_aliases
from wealth_ledger.workspace import CODE_ROOT, resolve_workspace, workspace_from_args


ROOT = CODE_ROOT


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.a = self.base / "portfolio-a"
        self.b = self.base / "portfolio-b"
        self.a.mkdir(); self.b.mkdir()

    def seed(self, root):
        rates = json.loads((ROOT / "examples/data/fx.json").read_text())
        import_holdings(root, ROOT / "examples/data/wealthsimple-holdings.csv", "baseline", rates)
        return make_payload(root)

    def test_resolution_never_creates_or_falls_back(self):
        with self.assertRaises(FileNotFoundError):
            workspace_from_args(ROOT, ["--workspace", str(self.base / "typo")])
        self.assertFalse((self.base / "typo").exists())
        (self.a / "unrelated.txt").write_text("unrelated")
        with self.assertRaisesRegex(ValueError, "no recognized"):
            resolve_workspace(ROOT, self.a)
        for args in (["--workspace"], ["--workspace="], ["--workspace", str(self.b), "--workspace", str(self.b)]):
            with self.assertRaises(ValueError):
                workspace_from_args(ROOT, args)
        self.assertEqual(resolve_workspace(ROOT).workspace_root, ROOT)
        self.assertEqual(workspace_from_args(ROOT, ["list", "--workspace=" + str(self.b)]).workspace_root, self.b.resolve())
        self.assertEqual(hashes(self.b), {})

    def test_render_cache_is_scoped_and_environment_restored(self):
        from wealth_ledger.reporting import _CACHE, _with_render_cache
        import matplotlib
        with patch.dict(os.environ, {"MPLCONFIGDIR": str(self.base / "host-cache")}):
            before = dict(os.environ)
            original_getter = matplotlib.get_cachedir
            @_with_render_cache
            def selected():
                return Path(matplotlib.get_cachedir()).resolve()
            for root in (self.a, self.b):
                token = _CACHE.set(root / "cache")
                try:
                    self.assertEqual(selected(), (root / "cache/matplotlib").resolve())
                finally:
                    _CACHE.reset(token)
                self.assertEqual(dict(os.environ), before)
            self.assertIs(matplotlib.get_cachedir, original_getter)

    @unittest.skipUnless(os.name == "posix", "Symlink permissions need POSIX")
    def test_workspace_rejects_state_symlink_escape(self):
        (self.a / "data").symlink_to(self.b, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "within"):
            resolve_workspace(ROOT, self.a)
        self.assertEqual(hashes(self.b), {})

    def test_preview_queries_backups_and_locks_are_isolated(self):
        self.seed(self.a)
        a = ApplicationService(resolve_workspace(ROOT, self.a))
        b = ApplicationService(resolve_workspace(ROOT, self.b))
        before = hashes(self.a)
        result = b.preview({"paths": [str(ROOT / "examples/data/wealthsimple-holdings.csv")]})
        self.assertIn(result["status"], ("ready", "pending_reference"))
        self.assertEqual(b.operations(), [])
        self.assertEqual(b.accounts(), [])
        self.assertEqual(hashes(self.b), {})
        self.assertEqual(hashes(self.a), before)
        self.assertIsNone(database_backup(self.b, "synthetic"))
        relative = database_backup(self.a, "synthetic")
        with closing(sqlite3.connect(self.a / relative)) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        from wealth_ledger.operations import project_lock
        with project_lock(self.a):
            with self.assertRaises(ValueError):
                with project_lock(self.a):
                    pass
            with project_lock(self.b):
                pass
        self.assertFalse((self.b / "data/db/portfolio.sqlite3").exists())

    def test_data_only_services_stay_in_selected_ledger(self):
        from wealth_ledger.wallet import add_balance, records
        self.seed(self.a); self.seed(self.b)
        a = ApplicationService(resolve_workspace(ROOT, self.a))
        before = hashes(self.b)
        result = a.record({"command": "synthetic-balance"}, lambda stage: add_balance(
            stage, "0.10000000", "2024-02-01T12:00:00-05:00", source="synthetic"), label="synthetic")
        self.assertFalse(result["report_published"])
        self.assertEqual(len(records(self.a, "balance")), 1)
        self.assertEqual(hashes(self.b), before)
        self.assertEqual(a.operation(result["operation_id"])["status"], "data_only_complete")

    def test_service_recovery_keeps_committed_operation_in_its_workspace(self):
        self.seed(self.a); self.seed(self.b)
        a = ApplicationService(resolve_workspace(ROOT, self.a))
        b = ApplicationService(resolve_workspace(ROOT, self.b))
        before_b = hashes(self.b)
        with patch("wealth_ledger.application.publish", side_effect=ValueError("synthetic report failure")):
            with self.assertRaisesRegex(ValueError, "--workspace"):
                a.update({"paths": [], "snapshot_id": 1})
        failed = a.operations()[0]
        self.assertEqual(failed["status"], "report_failed")
        committed = fingerprint(self.a)
        with self.assertRaises(ValueError):
            b.operation(failed["operation_id"])
        with patch("wealth_ledger.application.publish", return_value={"output": "synthetic-output"}) as publisher:
            result = a.update({}, resume=failed["operation_id"])
        self.assertEqual(publisher.call_args.args[0], self.a.resolve())
        self.assertEqual(result["status"], "published")
        self.assertEqual(fingerprint(self.a), committed)
        self.assertEqual(len(a.operations()), 1)
        self.assertEqual(hashes(self.b), before_b)

    def test_alias_fallback_override_hashes_and_conflicts(self):
        original, evidence = company_aliases(self.a)
        self.assertEqual(evidence["effective_sha256"], __import__("wealth_ledger.lookthrough", fromlist=["digest"]).digest(original))
        self.assertIsNone(evidence["override_sha256"])
        config = self.a / "config"; config.mkdir()
        path = config / "company-aliases.override.json"
        change = {"schema_version": 1, "companies": [{"id": "synthetic", "name": "Synthetic Example", "aliases": ["Synthetic Holdings"]}]}
        path.write_text(json.dumps(change))
        merged, changed = company_aliases(self.a)
        self.assertNotEqual(changed["effective_sha256"], evidence["effective_sha256"])
        self.assertEqual(merged["companies"][-1]["id"], "synthetic")
        self.assertEqual(changed["override_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        change["companies"][0]["aliases"] = [original["companies"][0]["name"]]
        path.write_text(json.dumps(change))
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            company_aliases(self.a)
        path.write_text('{"schema_version":99,"companies":[]}')
        with self.assertRaises(ValueError):
            company_aliases(self.a)

    def test_cli_subcommands_use_workspace_locale_and_no_checkout_mutation(self):
        self.seed(self.a)
        config = self.a / "config"; config.mkdir(exist_ok=True)
        (config / "local.toml").write_text('[reporting]\nlocale="en-CA"\n')
        for script, args in (("update.py", ["--list-operations"]),
                             ("btc_balances.py", ["list"]), ("btc_events.py", ["list"]),
                             ("crypto_opening.py", ["show"]), ("cash_flows.py", ["accounts"])):
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / script),
                *args, "--workspace", str(self.a)], capture_output=True, text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(result.returncode, 0, result.stderr)
            json.loads(result.stdout)
        self.assertEqual(hashes(self.b), {})
        result = subprocess.run([sys.executable, str(ROOT / "scripts/cash_flows.py"),
            "--workspace", str(self.b), "accounts"], capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])
        self.assertEqual(hashes(self.b), {})

    @unittest.skipUnless(os.name == "posix", "Read-only code permissions need POSIX")
    def test_copy_adoption_and_three_formats_from_read_only_code(self):
        """Real report generation in a child process with OS-enforced code permissions."""
        from test_lookthrough import fund
        payload = self.seed(self.a)
        attach_analysis(self.a, payload, fetcher=lambda id, directory: fund(id, []))
        original_signature = portfolio_signature(payload)
        before = hashes(self.a)
        shutil.copytree(self.a, self.b, dirs_exist_ok=True)
        self.assertEqual(fingerprint(self.a), fingerprint(self.b))
        self.assertEqual(portfolio_signature(make_payload(self.b)), original_signature)
        code = self.base / "readonly-code"; code.mkdir()
        for name in ("src", "scripts", "assets/fonts"):
            shutil.copytree(ROOT / name, code / name, ignore=shutil.ignore_patterns("__pycache__"))
        (code / "config").mkdir()
        shutil.copy2(ROOT / "config/company-aliases.json", code / "config/company-aliases.json")
        code_before = hashes(code)
        for path in code.rglob("*"):
            path.chmod(0o555 if path.is_dir() else 0o444)
        code.chmod(0o555)
        try:
            if os.geteuid() != 0:
                with self.assertRaises(PermissionError):
                    (code / "forbidden-write").write_text("fail")
            command = [sys.executable, str(code / "scripts/update.py"), "--workspace", str(self.b),
                       "--snapshot-id", "1", "--lookthrough-run-id", str(payload["lookthrough"]["run_id"]), "--locale", "en-CA"]
            result = subprocess.run(command, capture_output=True, text=True, timeout=120,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "MPLCONFIGDIR": str(code / "forbidden-cache")})
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads(result.stdout)
            output = Path(saved["output"])
            for name in ("report.md", "report.pdf", "portfolio.ods"):
                self.assertGreater((output / name).stat().st_size, 0)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["financial_fingerprint"], original_signature)
            self.assertEqual(manifest["workbook_validation"]["cache_mismatches"], 0)
            self.assertEqual(hashes(code), code_before)
            self.assertEqual(hashes(self.a), before)
            self.assertTrue((self.b / "work/cache/matplotlib").is_dir())
            self.assertEqual(ApplicationService(resolve_workspace(ROOT, self.a)).operations(), [])
        finally:
            code.chmod(0o755)
            for path in code.rglob("*"):
                path.chmod(0o755 if path.is_dir() else 0o644)


if __name__ == "__main__":
    unittest.main()
