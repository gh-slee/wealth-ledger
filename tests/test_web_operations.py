"""Synthetic upgrade, capacity and abrupt interruption acceptance; no live ledgers."""
import asyncio
from contextlib import closing
import errno
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

import test_web as foundation
import test_web_backups as backups_tests

if foundation.AVAILABLE:
    from wealth_ledger.operations import atomic_data, fingerprint
    from wealth_ledger.web.backups import backup_instance, restore_instance, database_info
    from wealth_ledger.web.maintenance import instance_activity, clear_maintenance
    from wealth_ledger.web.storage import prepare_instance, upgrade_instance, Store
    from wealth_ledger.web.uploads import receive_upload
    from wealth_ledger.locking import LockBusy

ROOT = Path(__file__).resolve().parents[1]


def full_disk():
    return OSError(errno.ENOSPC, "Synthetic disk capacity exhausted")


@unittest.skipUnless(foundation.AVAILABLE, "Optional Web dependencies are not installed")
class OperationsTests(unittest.TestCase):
    setUp = foundation.WebTests.setUp
    bootstrap = foundation.WebTests.bootstrap
    login = foundation.WebTests.login
    mutate = foundation.WebTests.mutate
    portfolio = foundation.WebTests.portfolio
    prepare = backups_tests.BackupTests.prepare

    def old_metadata(self):
        self.prepare()
        with closing(sqlite3.connect(self.store.db)) as conn, conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DROP TABLE jobs")
            conn.execute("DROP TABLE uploads")
            conn.execute("PRAGMA user_version=1")
        for path in (self.root / "admin/backups").glob("*.sqlite3"):
            path.unlink()
        return database_info(self.store.db)

    def test_upgrade_preserves_auth_registry_and_finance_and_is_idempotent(self):
        before = self.old_metadata()
        financial = fingerprint(self.project)
        report = (self.folder / "data.json").read_bytes()
        upgrade_instance(self.settings)
        snapshots = list((self.root / "admin/backups").glob("app-v1-*.sqlite3"))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(database_info(snapshots[0]), before)
        with closing(Store(self.settings).connect()) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0],
                             before["table_rows"]["artifacts"])
        self.assertEqual(fingerprint(self.project), financial)
        self.assertEqual((self.folder / "data.json").read_bytes(), report)
        self.assertEqual(self.client.get("/api/v1/auth/session").status_code, 200)
        after = database_info(self.store.db)
        upgrade_instance(self.settings)
        self.assertEqual(database_info(self.store.db), after)
        self.assertEqual(list((self.root / "admin/backups").glob("app-v1-*.sqlite3")), snapshots)

    def test_upgrade_refuses_future_schema_without_changing_values(self):
        self.prepare()
        with closing(sqlite3.connect(self.store.db)) as conn, conn:
            conn.execute("PRAGMA user_version=999")
        before = database_info(self.store.db)
        financial = fingerprint(self.project)
        with self.assertRaisesRegex(ValueError, "do not downgrade"):
            upgrade_instance(self.settings)
        self.assertEqual(database_info(self.store.db), before)
        self.assertEqual(fingerprint(self.project), financial)
        self.assertFalse((self.root / "admin/maintenance.json").exists())

    def test_upgrade_blocks_active_clients_and_cleans_its_barrier(self):
        self.prepare()
        # Context inheritance would permit nested activity; another process is a real peer.
        code = '''from pathlib import Path
from wealth_ledger.web.maintenance import instance_activity
import sys
with instance_activity(Path(sys.argv[1])):
    print("held", flush=True)
    sys.stdin.readline()
'''
        with subprocess.Popen([sys.executable, "-c", code, str(self.root)],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as child:
            try:
                self.assertEqual(child.stdout.readline().strip(), "held")
                with self.assertRaises(LockBusy):
                    upgrade_instance(self.settings, timeout=0)
                self.assertFalse((self.root / "admin/maintenance.json").exists())
            finally:
                child.communicate("done\n", timeout=10)
        upgrade_instance(self.settings, timeout=0)

    def test_upgrade_backup_failure_precedes_any_schema_mutation(self):
        before = self.old_metadata()
        original = sqlite3.connect
        class Connection(sqlite3.Connection):
            def backup(self, target, *args, **kwargs):
                raise full_disk()
        with patch("wealth_ledger.web.storage.sqlite3.connect",
                   side_effect=lambda *a, **k: original(*a, **k, factory=Connection)):
            with self.assertRaises(OSError):
                upgrade_instance(self.settings)
        self.assertEqual(database_info(self.store.db), before)
        self.assertFalse((self.root / "admin/maintenance.json").exists())
        upgrade_instance(self.settings)
        self.assertEqual(Store(self.settings).portfolios()[0]["id"], self.pid)

    def test_interrupted_upgrade_rolls_back_then_can_clear_barrier_and_retry(self):
        before = self.old_metadata()
        code = '''import os, sqlite3, sys
from pathlib import Path
from unittest.mock import patch
from wealth_ledger.web.config import WebSettings
from wealth_ledger.web.storage import upgrade_instance
original = sqlite3.connect
class Connection(sqlite3.Connection):
    def executescript(self, script):
        super().executescript(script.split("CREATE TABLE jobs")[0])
        os._exit(77)
with patch("wealth_ledger.web.storage.sqlite3.connect", side_effect=lambda *a, **k: original(*a, **k, factory=Connection)):
    upgrade_instance(WebSettings(Path(sys.argv[1])))
'''
        child = subprocess.run([sys.executable, "-c", code, str(self.root)], capture_output=True)
        self.assertEqual(child.returncode, 77, child.stderr.decode())
        self.assertEqual(database_info(self.store.db), before)
        self.assertTrue((self.root / "admin/maintenance.json").exists())
        result = subprocess.run([sys.executable, str(ROOT / "scripts/web.py"), "--data-root", str(self.root),
                                 "maintenance-clear"], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        upgrade_instance(self.settings)
        Store(self.settings)

    def test_staging_capacity_failure_cleans_partial_copy_and_never_calls_importer(self):
        self.prepare()
        before = fingerprint(self.project)
        def fail(source, target, *args, **kwargs):
            Path(target).mkdir(parents=True, exist_ok=True)
            (Path(target) / "partial").write_bytes(b"incomplete")
            raise full_disk()
        with patch("wealth_ledger.operations.shutil.copytree", side_effect=fail):
            with self.assertRaises(OSError):
                atomic_data(self.project, lambda _: self.fail("Importer must not run"))
        self.assertFalse(list((self.project / "work").glob("input-stage-*")))
        self.assertEqual(fingerprint(self.project), before)
        self.assertEqual(atomic_data(self.project, lambda _: {"retry": True}), {"retry": True})

    def test_immutable_evidence_capacity_failure_does_not_poison_retry(self):
        self.prepare()
        before = fingerprint(self.project)
        original = shutil.copy2
        def action(stage):
            (stage / "data/raw/new-evidence.txt").write_bytes(b"complete synthetic evidence")
            return {"done": True}
        def fail(source, target, *args, **kwargs):
            if Path(target).name.startswith(".evidence-"):
                Path(target).write_bytes(b"partial")
                raise full_disk()
            return original(source, target, *args, **kwargs)
        with patch("wealth_ledger.operations.shutil.copy2", side_effect=fail):
            with self.assertRaises(OSError):
                atomic_data(self.project, action)
        self.assertFalse((self.project / "data/raw/new-evidence.txt").exists())
        self.assertFalse(list((self.project / "data").rglob(".evidence-*")))
        self.assertEqual(fingerprint(self.project), before)
        atomic_data(self.project, action)
        self.assertEqual((self.project / "data/raw/new-evidence.txt").read_bytes(), b"complete synthetic evidence")

    def test_upload_capacity_failure_leaves_no_partial_file_or_metadata(self):
        self.prepare()
        class Request:
            headers = {"content-type": "application/json"}
            async def stream(self):
                yield b'{"partial":'
                raise full_disk()
        with self.assertRaises(OSError):
            asyncio.run(receive_upload(self.store, self.pid, Request(), "fx", "synthetic.json", 1))
        self.assertEqual(list((self.root / "uploads" / self.pid).iterdir()), [])
        with closing(self.store.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0], 0)

    def test_backup_capacity_failure_keeps_source_and_no_archive_then_retries(self):
        self.prepare()
        before = database_info(self.store.db)
        finance = fingerprint(self.project)
        with patch.object(zipfile.ZipFile, "write", side_effect=full_disk()):
            with self.assertRaises(OSError):
                backup_instance(self.settings, self.archive)
        self.assertFalse(self.archive.exists())
        self.assertFalse(list(self.archive.parent.glob(".private-backup.zip-*")))
        self.assertFalse(list((self.root / "cache").glob("backup-stage-*")))
        self.assertFalse((self.root / "admin/maintenance.json").exists())
        self.assertEqual(database_info(self.store.db), before)
        self.assertEqual(fingerprint(self.project), finance)
        backup_instance(self.settings, self.archive)
        restore_instance(self.target, self.archive)

    def test_restore_capacity_failure_leaves_empty_target_and_preserves_archive(self):
        self.prepare()
        backup_instance(self.settings, self.archive)
        saved = self.archive.read_bytes()
        original = Path.open
        def fail(path, *args, **kwargs):
            if ".restore-" in str(path) and args and args[0] == "xb":
                raise full_disk()
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", fail):
            with self.assertRaises(OSError):
                restore_instance(self.target, self.archive)
        self.assertEqual(list(self.target.data_root.iterdir()), [])
        self.assertEqual(self.archive.read_bytes(), saved)
        restore_instance(self.target, self.archive)
        self.assertEqual(fingerprint(Store(self.target).portfolio(self.pid)[1]), fingerprint(self.project))

    def test_abrupt_backup_exit_retains_barrier_without_publishing_partial_archive(self):
        self.prepare()
        finance = fingerprint(self.project)
        code = """import os, sys
from pathlib import Path
from unittest.mock import patch
from wealth_ledger.web.config import WebSettings
from wealth_ledger.web.backups import backup_instance
with patch("zipfile.ZipFile.write", side_effect=lambda *a, **k: os._exit(77)):
    backup_instance(WebSettings(Path(sys.argv[1])), Path(sys.argv[2]))
"""
        result = subprocess.run([sys.executable, "-c", code, str(self.root), str(self.archive)], capture_output=True)
        self.assertEqual(result.returncode, 77, result.stderr.decode())
        self.assertFalse(self.archive.exists())
        self.assertEqual(fingerprint(self.project), finance)
        self.assertTrue((self.root / "admin/maintenance.json").exists())
        clear_maintenance(self.root)
        backup_instance(self.settings, self.archive)
        restore_instance(self.target, self.archive)

    def test_abrupt_restore_exit_fails_closed_and_archive_can_restore_to_another_empty_root(self):
        self.prepare()
        backup_instance(self.settings, self.archive)
        saved = self.archive.read_bytes()
        code = """import os, sys
from pathlib import Path
from unittest.mock import patch
from wealth_ledger.web.config import WebSettings
from wealth_ledger.web.backups import restore_instance
original = os.replace
root = Path(sys.argv[1])
def interrupt(source, destination):
    original(source, destination)
    if Path(destination).parent == root:
        os._exit(77)
with patch("wealth_ledger.web.backups.os.replace", side_effect=interrupt):
    restore_instance(WebSettings(root), Path(sys.argv[2]))
"""
        result = subprocess.run([sys.executable, "-c", code, str(self.target.data_root), str(self.archive)], capture_output=True)
        self.assertEqual(result.returncode, 77, result.stderr.decode())
        self.assertFalse((self.target.data_root / "admin/instance.json").exists())
        with self.assertRaises(ValueError):
            Store(self.target)
        with self.assertRaisesRegex(ValueError, "empty"):
            restore_instance(self.target, self.archive)
        self.assertEqual(self.archive.read_bytes(), saved)
        from wealth_ledger.web.config import WebSettings
        other = WebSettings(self.root.parent / "another-empty-root")
        restore_instance(other, self.archive)
        self.assertEqual(fingerprint(Store(other).portfolio(self.pid)[1]), fingerprint(self.project))
