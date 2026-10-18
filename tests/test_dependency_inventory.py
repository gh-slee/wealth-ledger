"""Dependency metadata inventory is deterministic, offline and fails on lock drift."""
from email.message import Message
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dependency_inventory import locked_python, npm_inventory, python_inventory


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "requirements.lock").write_text("example-lib==1.2.3\n")
        (self.root / "requirements-web.lock").write_text("-r requirements.lock\nweb-lib==2.0\n")

    def distribution(self, name):
        class Distribution:
            files = []
            metadata = Message()
        result = Distribution()
        result.version = {"example-lib": "1.2.3", "web-lib": "2.0"}[name]
        result.metadata["License-Expression"] = "MIT"
        return result

    def test_nested_exact_pins_and_metadata_are_stable(self):
        expected = {"example-lib": "1.2.3", "web-lib": "2.0"}
        self.assertEqual(locked_python(self.root, "requirements-web.lock"), expected)
        rows = python_inventory(self.root, "requirements-web.lock", self.distribution)
        self.assertEqual(rows, python_inventory(self.root, "requirements-web.lock", self.distribution))
        self.assertTrue(all(row["license_declared"] for row in rows))
        self.assertNotIn(str(self.root), json.dumps(rows))

    def test_missing_license_stays_unknown_and_version_drift_fails(self):
        def unknown(name):
            result = self.distribution(name)
            result.metadata = Message()
            return result
        self.assertFalse(python_inventory(self.root, "requirements.lock", unknown)[0]["license_declared"])
        (self.root / "requirements.lock").write_text("example-lib==9.0\n")
        with self.assertRaisesRegex(ValueError, "differs"):
            python_inventory(self.root, "requirements.lock", self.distribution)

    def test_unpinned_conflicts_and_recursive_paths_fail(self):
        for text in ("example-lib>=1", "-r requirements-web.lock", "-r ../private.lock",
                     "example_lib==1\nexample-lib==2"):
            with self.subTest(text=text):
                (self.root / "requirements.lock").write_text(text)
                with self.assertRaises(ValueError):
                    locked_python(self.root, "requirements-web.lock")

    def test_npm_includes_optional_development_and_unknown_license_scope(self):
        directory = self.root / "frontend"; directory.mkdir()
        path = directory / "package-lock.json"
        lock = {"lockfileVersion": 3, "packages": {"": {},
            "node_modules/@example/library": {"version": "1.0", "license": "MIT", "integrity": "sha512-example"},
            "node_modules/tool": {"version": "2.0", "optional": True, "dev": True, "os": ["linux"], "cpu": ["arm64"]}}}
        path.write_text(json.dumps(lock))
        rows = npm_inventory(self.root)
        self.assertEqual(rows[0]["name"], "@example/library")
        self.assertTrue(rows[1]["optional"] and rows[1]["development_only"])
        self.assertFalse(rows[1]["license_declared"])
        lock["packages"]["../private"] = {"version": "1"}
        path.write_text(json.dumps(lock))
        with self.assertRaises(ValueError):
            npm_inventory(self.root)
