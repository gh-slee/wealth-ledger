"""Offline source-plan evidence, actual code digests and isolated execution tests."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import venv

from test_source_protocol import ACCOUNT, AT, EVIDENCE, HOLDING, INFO, batch
from wealth_ledger.source_environment import EnvironmentError, environment_fingerprint
from wealth_ledger.source_pipeline import (
    DEFAULT_CONFIG, SourcePlanError, _json, _plan, bounded_read, host_config,
    parse_config, plan_sources, validate_inputs, validate_receipt,
)
from wealth_ledger.source_registry import AdapterRegistration, ProviderInfo, build_registry
from wealth_ledger.source_protocol import Detection

ROOT = Path(__file__).resolve().parents[1]
RAW = b"symbol,quantity\nDEMO,1.25\n"


class Synthetic:
    info = INFO
    def detect(self, raw):
        return Detection(True, "2024-v1", "Synthetic CSV")
    def normalize(self, raw, *, export_version):
        return replace(batch(HOLDING), evidence=replace(EVIDENCE, raw_sha256=hashlib.sha256(raw).hexdigest()))


def synthetic_plan(raw=RAW, config=DEFAULT_CONFIG, selections=None, adapter=None, environment="a" * 64):
    registry = build_registry(builtins=(AdapterRegistration(ProviderInfo("synthetic", "Synthetic Bank"), adapter or Synthetic()),))
    return _plan((raw,), config, selections or {}, registry=registry, environment=environment)


class SourcePipelineTests(unittest.TestCase):
    def assert_code(self, code, action):
        with self.assertRaises(SourcePlanError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def test_plan_is_reproducible_nonbooking_and_contains_only_summary(self):
        first, second = synthetic_plan(), synthetic_plan()
        self.assertEqual(first, second)
        self.assertFalse(first["ingestible"])
        self.assertEqual(first["booking_blocker"], "protocol_v1_not_bookable")
        self.assertEqual(first["inputs"][0]["record_counts"], {"holdings": 1})
        self.assertNotIn("records", first["inputs"][0])
        self.assertNotIn(ACCOUNT.account_id, json.dumps(first))
        self.assertEqual(validate_receipt(first), first)

    def test_input_config_mapping_selection_and_code_changes_change_fingerprint(self):
        original = synthetic_plan()
        config = json.dumps({"schema_version": 1, "enabled": [], "bindings": [
            {"provider_id": "synthetic", "source_account_id": "account-001", "ledger_account_id": "existing-ledger"}]}).encode()
        changed = [synthetic_plan(raw=RAW + b"DEMO,2\n"), synthetic_plan(config=config),
                   synthetic_plan(selections={"1": INFO.adapter_id}), synthetic_plan(environment="b" * 64)]
        self.assertTrue(all(item["fingerprint"] != original["fingerprint"] for item in changed))
        self.assertNotIn("existing-ledger", json.dumps(changed[1]))

    def test_wrong_or_tampered_receipts_fail(self):
        original = synthetic_plan()
        for value in (None, {}, {**original, "ingestible": True}, {**original, "fingerprint": "0" * 64},
                      {**original, "environment_sha256": "not a digest"}, {**original, "schema_version": True}):
            self.assert_code("invalid_plan", lambda: validate_receipt(value))

    def test_strict_configuration_rejects_code_paths_duplicate_keys_and_bad_bindings(self):
        parse_config(DEFAULT_CONFIG)
        bad = [b'{"schema_version":1,"schema_version":1,"enabled":[],"bindings":[]}',
               b'{"schema_version":true,"enabled":[],"bindings":[]}',
               b'{"schema_version":1,"enabled":[],"bindings":[],"module":"arbitrary:code"}',
               b'{"schema_version":1,"enabled":[{"distribution":"../file","version":"1","entry_point":"demo","adapter_id":"demo"}],"bindings":[]}']
        binding = {"provider_id": "synthetic", "source_account_id": "alias", "ledger_account_id": "a"}
        bad.append(json.dumps({"schema_version":1,"enabled":[],"bindings":[binding,binding]}).encode())
        for raw in bad:
            self.assert_code("invalid_configuration", lambda: parse_config(raw))

    def test_input_bounds_and_slot_selection(self):
        validate_inputs((RAW,), {})
        for raw in (b"a,a\n1,2\n", b"a\n", b"a\n\x00\n", b"\xff\n", b"a\n\"unterminated"):
            self.assert_code("invalid_inputs", lambda: validate_inputs((raw,), {}))
        for inputs, choices in (((), {}), ((RAW,) * 6, {}), ((RAW,), {"2": "adapter"}), ((RAW,), {"1": 2}), ((RAW,), {"1": "x"*201})):
            self.assert_code("invalid_inputs", lambda: validate_inputs(inputs, choices))

    def test_normalization_hash_identity_and_errors_are_checked(self):
        class Wrong(Synthetic):
            def normalize(self, raw, *, export_version):
                value = super().normalize(raw, export_version=export_version)
                return replace(value, adapter=replace(INFO, adapter_version="changed"))
        self.assert_code("normalization_identity", lambda: synthetic_plan(adapter=Wrong()))
        class Broken(Synthetic):
            def normalize(self, raw, *, export_version):
                raise RuntimeError("synthetic-private-row")
        self.assert_code("normalization_failed", lambda: synthetic_plan(adapter=Broken()))
        with patch("wealth_ledger.source_pipeline.NORMALIZED_BYTES", 1):
            self.assert_code("normalization_limits", synthetic_plan)

    def test_environment_tracks_actual_same_version_code_and_unlisted_dependency_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"; site.mkdir()
            runtime = root / "python"; runtime.write_bytes(b"runtime")
            module = site / "demo.py"; module.write_bytes(b"value = 1")
            capture = lambda: environment_fingerprint(roots={"site": site}, executable=runtime)
            first = capture()
            module.write_bytes(b"value = 2")
            self.assertNotEqual(capture(), first)
            second = capture()
            (site / "new_dependency.py").write_bytes(b"value = 1")
            self.assertNotEqual(capture(), second)
            cache = site / "__pycache__"; cache.mkdir()
            third = capture()
            (cache / "ignored.pyc").write_bytes(b"cache is not executed by fresh isolated children")
            self.assertEqual(capture(), third)

    def test_environment_fails_on_escapes_hooks_limits_or_unreadable_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"; site.mkdir()
            runtime = root / "python"; runtime.write_bytes(b"runtime")
            file = site / "module.py"; file.write_bytes(b"x=1")
            capture = lambda: environment_fingerprint(roots={"site":site}, executable=runtime)
            hook = site / "hook.pth"; hook.write_text("import unknown_startup_code")
            with self.assertRaises(EnvironmentError): capture()
            hook.unlink()
            link = site / "external.py"; link.symlink_to(runtime)
            with self.assertRaises(EnvironmentError): capture()
            link.unlink()
            with patch("wealth_ledger.source_environment.MAX_CODE_BYTES", 1), self.assertRaises(EnvironmentError): capture()
            with self.assertRaises(EnvironmentError): environment_fingerprint(roots={"missing":root/"missing"}, executable=runtime)

    def test_bounded_evidence_and_missing_config_do_not_initialize_any_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(host_config(root/"missing.json"), DEFAULT_CONFIG)
            source = root/"source.csv"; source.write_bytes(RAW)
            self.assert_code("invalid_evidence", lambda: bounded_read(source, 1))
            link = root/"link.csv"; link.symlink_to(source)
            self.assert_code("invalid_evidence", lambda: bounded_read(link, 1000))
            self.assert_code("invalid_timeout", lambda: plan_sources([source], timeout=float("nan")))
            self.assert_code("invalid_inputs", lambda: plan_sources([]))
            broken = root/"broken.json"; broken.symlink_to(root/"absent.json")
            self.assert_code("invalid_configuration", lambda: host_config(broken))
            self.assertFalse((root/"data").exists())


PLUGIN = '''from datetime import datetime
from decimal import Decimal
import hashlib
from wealth_ledger.source_protocol import *
from wealth_ledger.source_registry import AdapterRegistration, ProviderInfo
class Demo:
    info = AdapterInfo("demo", "demo.holdings", "1.0.0", ("csv-v1",), ("holdings",))
    def detect(self, raw):
        ok = raw.startswith(b"symbol,quantity")
        return Detection(ok, "csv-v1" if ok else None, "Synthetic format")
    def normalize(self, raw, *, export_version):
        at = datetime.fromisoformat("2024-01-31T17:00:00-05:00")
        account = AccountKey("demo", "example-account")
        holding = Holding(RecordKey(account, "position", "1"), at,
            AssetKey("security", "DEMO", "CAD", market="XTSE"), Decimal("1.25"), Money(Decimal("10"), "CAD"), None)
        evidence = SourceEvidence(hashlib.sha256(raw).hexdigest(), at, at, "synthetic-export", (), (), "synthetic stable ID")
        coverage = Coverage("holdings", account, at, at, "partial", "synthetic", "scope", "1")
        return NormalizedBatch(self.info, export_version, evidence, (coverage,), (holding,))
def make(): return AdapterRegistration(ProviderInfo("demo", "Demo Bank"), Demo())
'''


class IsolatedPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="source-plan-synthetic-")
        cls.root = Path(cls.temp.name)
        cls.env = cls.root / "venv"
        venv.EnvBuilder(with_pip=False).create(cls.env)
        cls.python = cls.env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        result = subprocess.run([str(cls.python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], check=True, capture_output=True, text=True)
        cls.site = Path(result.stdout.strip())
        cls.info = cls.site / "demo_parser-1.0.0.dist-info"; cls.info.mkdir()
        (cls.info/"METADATA").write_text("Metadata-Version: 2.1\nName: demo-parser\nVersion: 1.0.0\n")
        (cls.info/"entry_points.txt").write_text("[wealth_ledger.source_adapters]\nholdings = synthetic_plan_plugin:make\n")

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        self.module = self.site / "synthetic_plan_plugin.py"
        self.module.write_text(PLUGIN)
        self.source = self.root / "source.csv"; self.source.write_bytes(RAW)
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({"schema_version":1,"enabled":[{"distribution":"demo-parser","version":"1.0.0","entry_point":"holdings","adapter_id":"demo.holdings"}],"bindings":[]}))
        extra=self.site/"added_dependency.py"
        extra.unlink(missing_ok=True)

    def plan(self, **kwargs):
        return plan_sources([self.source], config_path=self.config, python=self.python, **kwargs)

    def test_real_child_loads_normalizes_revalidates_and_never_books(self):
        value = self.plan()
        self.assertEqual(self.plan(previous=value), value)
        self.assertFalse(value["ingestible"])
        self.assertEqual(value["inputs"][0]["adapter"]["provider_id"], "demo")
        self.assertFalse((self.root/"data").exists())
        self.assertNotIn("synthetic_plan_plugin", sys.modules)
        self.assertFalse(list(self.site.rglob("*.pyc")))
        # Valid UTF-8 configuration may expand substantially in private JSON IPC.
        config=json.loads(self.config.read_text())
        config["bindings"]=[{"provider_id":"demo","source_account_id":chr(233)*100+str(n),
                             "ledger_account_id":chr(233)*100} for n in range(80)]
        self.config.write_text(json.dumps(config,ensure_ascii=False),encoding="utf-8")
        expanded=self.plan()
        self.assertEqual(expanded["configuration_sha256"],hashlib.sha256(self.config.read_bytes()).hexdigest())

    def test_same_version_plugin_dependency_input_and_config_changes_reject_old_plan(self):
        original=self.plan()
        for mutation, restore in (
            (lambda:self.module.write_text(PLUGIN+"\n# same-version code edit\n"),lambda:self.module.write_text(PLUGIN)),
            (lambda:(self.site/"added_dependency.py").write_text("x=1"),lambda:(self.site/"added_dependency.py").unlink()),
            (lambda:self.source.write_bytes(RAW+b"DEMO,2\n"),lambda:self.source.write_bytes(RAW)),
            (lambda:self.config.write_bytes(self.config.read_bytes()+b"\n"),lambda:self.setUp())):
            mutation()
            with self.assertRaisesRegex(SourcePlanError,"stale_plan"):
                self.plan(previous=original)
            restore()
        with self.assertRaisesRegex(SourcePlanError,"stale_environment"):
            self.plan(expected_environment="0"*64)

    def test_child_wall_timeout_and_plugin_errors_are_redacted(self):
        with self.assertRaisesRegex(SourcePlanError,"parser_timeout"):
            self.plan(timeout=0.01)
        self.module.write_text("raise RuntimeError('synthetic-private-source-row')\n")
        with self.assertRaises(SourcePlanError) as caught: self.plan()
        self.assertEqual(caught.exception.code,"plugin_load_failed")
        self.assertNotIn("synthetic-private-source-row",str(caught.exception))

    def test_cli_and_shared_runner_have_identical_plan_and_verify_results(self):
        expected=self.plan()
        command=[str(self.python),str(ROOT/"scripts/source_parsers.py"),str(self.source),"--config",str(self.config)]
        result=subprocess.run(command,check=True,text=True,capture_output=True)
        self.assertEqual(json.loads(result.stdout),expected)
        saved=self.root/"plan.json"; saved.write_text(result.stdout)
        result=subprocess.run([*command,"--verify",str(saved)],check=True,text=True,capture_output=True)
        self.assertEqual(json.loads(result.stdout),expected)
        saved.write_text("["*2000+"0"+"]"*2000)
        rejected=subprocess.run([*command,"--verify",str(saved)],text=True,capture_output=True)
        self.assertEqual(rejected.returncode,2)
        self.assertEqual(json.loads(rejected.stdout)["error"],"invalid_request")
        self.assertNotIn("Traceback",rejected.stderr)


if __name__ == "__main__": unittest.main()
