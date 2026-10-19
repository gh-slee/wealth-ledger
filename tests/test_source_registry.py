"""Synthetic registry acceptance; no installed third-party code or financial data."""
from dataclasses import replace
from importlib import metadata
from pathlib import Path
import sys
import tempfile
import traceback
import unittest
from unittest.mock import patch

from wealth_ledger.source_protocol import AdapterInfo, Detection
from wealth_ledger.source_registry import (
    ENTRY_POINT_GROUP, MAX_INPUT_BYTES, AdapterRegistration, PluginCandidate,
    PluginSelection, ProviderInfo, RegistryError, build_registry, discover_plugins,
)


INFO = AdapterInfo("demo", "demo.holdings", "1.0.0", ("csv-v1",), ("holdings",))
PROVIDER = ProviderInfo("demo", "Demo Bank")
SELECTION = PluginSelection("demo-parser", "1.2.3", "holdings", INFO.adapter_id)


class Adapter:
    def __init__(self, info=INFO, result=None):
        self.info = info
        self.result = result or Detection(True, "csv-v1", "Synthetic exact format")
        self.calls = 0

    def detect(self, raw):
        self.calls += 1
        return self.result

    def normalize(self, raw, *, export_version):
        raise AssertionError("Registry detection must not normalize or submit records")


def registration(info=INFO, *, provider=PROVIDER, adapter=None):
    return AdapterRegistration(provider, adapter or Adapter(info))


def candidate(distribution="demo-parser", version="1.2.3", name="holdings", target="synthetic_plugin:make"):
    point = metadata.EntryPoint(name=name, value=target, group=ENTRY_POINT_GROUP)
    return PluginCandidate(distribution, version, name, target, point)


class Distribution:
    def __init__(self, name="demo-parser", version="1.2.3", points=None):
        self.metadata = {"Name": name}
        self.version = version
        self.entry_points = (candidate()._entry_point,) if points is None else points


class SourceRegistryTests(unittest.TestCase):
    def assert_code(self, expected, action):
        with self.assertRaises(RegistryError) as caught:
            action()
        self.assertEqual(caught.exception.code, expected)
        return caught.exception

    def test_default_registry_does_not_discover_or_import_packages(self):
        with patch("wealth_ledger.source_registry.metadata.distributions", side_effect=AssertionError("No discovery")):
            registry = build_registry()
        self.assertEqual(registry.adapters, ())
        self.assert_code("no_match", lambda: registry.detect(b"demo"))

    def test_builtin_and_same_provider_multiple_formats_use_one_registry(self):
        first = registration()
        second = registration(replace(INFO, adapter_id="demo.activity", kinds=("cash_flows",)))
        registry = build_registry(builtins=(first, second))
        self.assertEqual([item.info.adapter_id for item in registry.adapters], ["demo.activity", "demo.holdings"])
        self.assertTrue(all(item.provider == PROVIDER and item.plugin is None for item in registry.adapters))
        self.assert_code("ambiguous_detection", lambda: registry.detect(b"demo"))
        match = registry.detect(b"demo", adapter_id="demo.holdings")
        self.assertEqual(match.export_version, "csv-v1")
        self.assertEqual(match.descriptor.info, INFO)

    def test_duplicate_adapter_and_conflicting_provider_metadata_fail(self):
        self.assert_code("duplicate_adapter", lambda: build_registry(builtins=(registration(), registration())))
        other = registration(replace(INFO, adapter_id="demo.other"), provider=replace(PROVIDER, display_name="Conflicting name"))
        self.assert_code("conflicting_provider", lambda: build_registry(builtins=(registration(), other)))
        self.assert_code("invalid_adapter", lambda: build_registry(builtins=(registration(provider=ProviderInfo("other", "Other")),)))

    def test_contract_compatibility_and_invalid_adapter_shapes(self):
        for info in (replace(INFO, api_version=3), replace(INFO, api_version=True)):
            self.assert_code("incompatible_adapter", lambda: build_registry(builtins=(registration(info),)))
        for item in ("not registration", registration(replace(INFO, kinds=("invalid",))),
                     registration(provider=ProviderInfo("demo", ""))):
            self.assert_code("invalid_adapter", lambda: build_registry(builtins=(item,)))
        adapter = Adapter()
        adapter.normalize = None
        self.assert_code("invalid_adapter", lambda: build_registry(builtins=(registration(adapter=adapter),)))

    def test_discovery_and_disabled_catalog_do_not_load_code(self):
        unrelated = metadata.EntryPoint(name="other", value="unrelated:run", group="console_scripts")
        with patch.object(metadata.EntryPoint, "load", side_effect=AssertionError("Disabled code executed")):
            found = discover_plugins((Distribution(points=(unrelated, candidate()._entry_point)),))
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].target, "synthetic_plugin:make")
            self.assertEqual(build_registry(catalog=found).adapters, ())

    def test_discovery_is_sorted_and_distribution_names_are_normalized(self):
        found = discover_plugins((Distribution("Zed_Parser"), Distribution("alpha.parser")))
        self.assertEqual([item.distribution for item in found], ["alpha.parser", "Zed_Parser"])
        with patch.object(metadata.EntryPoint, "load", return_value=lambda: registration()) as load:
            registry = build_registry(enabled=(replace(SELECTION, distribution="DEMO_Parser"),), catalog=(candidate(),))
        load.assert_called_once()
        self.assertEqual(registry.adapters[0].plugin.distribution, "DEMO_Parser")

    def test_colliding_entry_points_fail_without_loading(self):
        with patch.object(metadata.EntryPoint, "load", side_effect=AssertionError("Unexpected load")):
            self.assert_code("ambiguous_plugin", lambda: discover_plugins((Distribution(), Distribution("Demo.Parser"))))
            self.assert_code("ambiguous_plugin", lambda: build_registry(catalog=(candidate(), candidate(version="2"))))

    def test_invalid_metadata_and_catalog_are_redacted(self):
        for item in (Distribution(name=None), Distribution(version=None), Distribution(points=(candidate(name="Invalid Name")._entry_point,))):
            self.assert_code("invalid_catalog", lambda: discover_plugins((item,)))
        bad = replace(candidate(), target="not the recorded target")
        self.assert_code("invalid_catalog", lambda: build_registry(catalog=(bad,)))
        with patch("wealth_ledger.source_registry.metadata.distributions", side_effect=RuntimeError("synthetic-sensitive-value")):
            error = self.assert_code("invalid_catalog", discover_plugins)
        self.assertNotIn("synthetic-sensitive-value", str(error))

    def test_exact_selection_loads_only_enabled_factory(self):
        with patch.object(metadata.EntryPoint, "load", return_value=lambda: registration()) as load:
            registry = build_registry(enabled=(SELECTION,), catalog=(candidate(), candidate("disabled-parser")))
        load.assert_called_once()
        self.assertEqual(registry.detect(b"demo").descriptor.plugin, SELECTION)

    def test_automatic_metadata_discovery_is_only_for_explicit_enablement(self):
        with patch("wealth_ledger.source_registry.metadata.distributions", return_value=(Distribution(),)) as discover:
            with patch.object(metadata.EntryPoint, "load", return_value=lambda: registration()):
                registry = build_registry(enabled=(SELECTION,))
        discover.assert_called_once()
        self.assertEqual(registry.adapters[0].info.adapter_id, INFO.adapter_id)

    def test_all_selections_validated_before_any_package_load(self):
        missing = replace(SELECTION, distribution="missing", adapter_id="other.holdings")
        with patch.object(metadata.EntryPoint, "load", side_effect=AssertionError("Premature load")):
            for enabled in ((SELECTION, missing), (replace(SELECTION, version="wrong"),)):
                self.assert_code("unavailable_plugin", lambda: build_registry(enabled=enabled, catalog=(candidate(),)))

    def test_enablement_collisions_and_bad_configuration_rejected(self):
        for enabled in ((SELECTION, SELECTION),):
            self.assert_code("duplicate_adapter", lambda: build_registry(enabled=enabled, catalog=(candidate(),)))
        duplicate_point = replace(SELECTION, adapter_id="demo.second")
        self.assert_code("ambiguous_plugin", lambda: build_registry(enabled=(SELECTION, duplicate_point), catalog=(candidate(),)))
        self.assert_code("duplicate_adapter", lambda: build_registry(builtins=(registration(),), enabled=(SELECTION,)))
        for kwargs in ({"builtins": []}, {"enabled": []}, {"catalog": []}, {"enabled": ("module:run",)},
                       {"enabled": (replace(SELECTION, distribution="../module"),)},
                       {"enabled": (replace(SELECTION, version=""),)}):
            self.assert_code("invalid_configuration", lambda: build_registry(**kwargs))

    def test_loaded_identity_and_protocol_must_match(self):
        for item, code in ((registration(replace(INFO, adapter_id="unexpected")), "invalid_adapter"),
                           (registration(replace(INFO, api_version=3)), "incompatible_adapter"),
                           (Adapter(), "invalid_adapter")):
            with patch.object(metadata.EntryPoint, "load", return_value=lambda: item):
                self.assert_code(code, lambda: build_registry(enabled=(SELECTION,), catalog=(candidate(),)))

    def test_builtin_external_provider_metadata_conflicts_fail(self):
        builtin = registration(replace(INFO, adapter_id="demo.builtin"))
        external = registration(provider=replace(PROVIDER, display_name="Other metadata"))
        with patch.object(metadata.EntryPoint, "load", return_value=lambda: external):
            self.assert_code("conflicting_provider", lambda: build_registry(builtins=(builtin,), enabled=(SELECTION,), catalog=(candidate(),)))

    def test_factory_failures_are_redacted_without_exception_chain(self):
        for loader in (RuntimeError("synthetic-sensitive-value"), lambda: (_ for _ in ()).throw(RuntimeError("synthetic-sensitive-value")), 42):
            with patch.object(metadata.EntryPoint, "load", **({"side_effect": loader} if isinstance(loader, Exception) else {"return_value": loader})):
                try:
                    build_registry(enabled=(SELECTION,), catalog=(candidate(),))
                except RegistryError as error:
                    self.assertEqual(error.code, "plugin_load_failed")
                    self.assertNotIn("synthetic-sensitive-value", "".join(traceback.format_exception(error)))
                else:
                    self.fail("Invalid factory accepted")

    def test_detection_failure_does_not_disappear_behind_another_match(self):
        class Broken(Adapter):
            def detect(self, raw):
                raise RuntimeError("synthetic-sensitive-value")
        registry = build_registry(builtins=(registration(), registration(replace(INFO, adapter_id="demo.zzbroken"), adapter=Broken(replace(INFO, adapter_id="demo.zzbroken")))))
        error = self.assert_code("detection_failed", lambda: registry.detect(b"demo"))
        self.assertNotIn("synthetic-sensitive-value", str(error))
        self.assertEqual(registry.detect(b"demo", adapter_id="demo.holdings").descriptor.info, INFO)

    def test_no_match_ambiguity_and_explicit_selection_are_deterministic(self):
        adapters = (registration(), registration(replace(INFO, adapter_id="demo.other")))
        for ordered in (adapters, tuple(reversed(adapters))):
            registry = build_registry(builtins=ordered)
            self.assert_code("ambiguous_detection", lambda: registry.detect(b"demo"))
            self.assertEqual(registry.detect(b"demo", adapter_id="demo.other").descriptor.info.adapter_id, "demo.other")
        nonmatch = Adapter(result=Detection(False, None, "Different format"))
        registry = build_registry(builtins=(registration(adapter=nonmatch),))
        self.assert_code("no_match", lambda: registry.detect(b"demo"))
        self.assert_code("no_match", lambda: registry.detect(b"demo", adapter_id=INFO.adapter_id))
        for selected in ("missing", "../module", ""):
            self.assert_code("unknown_adapter", lambda: registry.detect(b"demo", adapter_id=selected))

    def test_malformed_detector_results_cannot_select_a_format(self):
        for result in ("not detection", Detection(1, "csv-v1", "Invalid bool"), Detection(True, "unknown", "Unsupported"),
                       Detection(False, "csv-v1", "Invalid nonmatch"), Detection(True, "csv-v1", "")):
            registry = build_registry(builtins=(registration(adapter=Adapter(result=result)),))
            self.assert_code("invalid_detection", lambda: registry.detect(b"demo"))

    def test_detection_is_bounded_and_does_not_normalize_or_mutate_catalog(self):
        adapter = Adapter()
        registry = build_registry(builtins=(registration(adapter=adapter),))
        for raw in (b"", bytearray(b"demo"), "demo", b"x" * (MAX_INPUT_BYTES + 1)):
            self.assert_code("invalid_input", lambda: registry.detect(raw))
        self.assertEqual(adapter.calls, 0)
        registry.detect(b"demo")
        adapter.info = replace(INFO, adapter_version="2.0.0")
        self.assert_code("invalid_adapter", lambda: registry.detect(b"demo"))
        self.assertEqual(registry.adapters[0].info.adapter_version, "1.0.0")

    def test_metadata_identity_changed_during_detection_is_rejected(self):
        class Changed(Adapter):
            def detect(self, raw):
                self.info = replace(INFO, kinds=("cash_flows",))
                return Detection(True, "csv-v1", "Synthetic")
        registry = build_registry(builtins=(registration(adapter=Changed()),))
        self.assert_code("invalid_adapter", lambda: registry.detect(b"demo"))

    def test_real_installed_metadata_entry_point_loads_only_after_enablement(self):
        module = "synthetic_registry_test_plugin"
        self.assertNotIn(module, sys.modules)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            info = root / "demo_parser-1.2.3.dist-info"
            info.mkdir()
            (info / "METADATA").write_text("Metadata-Version: 2.1\nName: demo-parser\nVersion: 1.2.3\n", encoding="utf-8")
            (info / "entry_points.txt").write_text(f"[{ENTRY_POINT_GROUP}]\nholdings = {module}:make\n", encoding="utf-8")
            (root / (module + ".py")).write_text(
                "from wealth_ledger.source_registry import AdapterRegistration, ProviderInfo\n"
                "from wealth_ledger.source_protocol import AdapterInfo, Detection\n"
                "class Demo:\n"
                "    info = AdapterInfo('demo', 'demo.holdings', '1.0.0', ('csv-v1',), ('holdings',))\n"
                "    def detect(self, raw): return Detection(raw == b'demo', 'csv-v1' if raw == b'demo' else None, 'Synthetic')\n"
                "    def normalize(self, raw, *, export_version): raise NotImplementedError\n"
                "def make(): return AdapterRegistration(ProviderInfo('demo', 'Demo Bank'), Demo())\n", encoding="utf-8")
            with patch.object(sys, "path", [directory, *sys.path]):
                found = discover_plugins((metadata.Distribution.at(info),))
                self.assertNotIn(module, sys.modules)
                build_registry(catalog=found)
                self.assertNotIn(module, sys.modules)
                try:
                    registry = build_registry(enabled=(SELECTION,), catalog=found)
                    self.assertIn(module, sys.modules)
                    self.assertEqual(registry.detect(b"demo").export_version, "csv-v1")
                    self.assert_code("no_match", lambda: registry.detect(b"other"))
                finally:
                    sys.modules.pop(module, None)


if __name__ == "__main__":
    unittest.main()
