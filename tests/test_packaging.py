"""Public build inputs and installed/source workspace boundaries, synthetic only."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wealth_ledger import workspace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("wealth_build_test", ROOT / "build_backend.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class PackagingTests(unittest.TestCase):
    def test_minimal_tree_excludes_private_files_even_if_present(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"; source.mkdir()
            # First prepare an audited public source tree, then contaminate it.
            backend.stage_source(ROOT, source)
            for name in ("AGENTS.override.md", "config/local.toml", "data/db/personal.sqlite3",
                         "reports/private.md", "src/wealth_ledger/private.json"):
                path = source / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("synthetic private sentinel")
            target = base / "target"; target.mkdir()
            backend.stage_source(source, target)
            self.assertFalse((target / "AGENTS.override.md").exists())
            self.assertFalse((target / "data").exists())
            self.assertFalse((target / "reports").exists())
            self.assertFalse((target / "config/local.toml").exists())
            self.assertFalse((target / "src/wealth_ledger/private.json").exists())
            self.assertTrue((target / "src/wealth_ledger/_bundle/assets/fonts/OFL.txt").is_file())

    def test_symlink_and_sensitive_public_code_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"; source.mkdir()
            backend.stage_source(ROOT, source)
            file = source / "src/wealth_ledger/__init__.py"
            file.unlink(); file.symlink_to(ROOT / "src/wealth_ledger/__init__.py")
            with self.assertRaises(ValueError):
                backend.stage_source(source, Path(directory) / "rejected")
            file.unlink(); file.write_text('# ' + 'PRIVATE_' + 'FINANCIAL_FIXTURE')
            with self.assertRaises(ValueError):
                backend.stage_source(source, Path(directory) / "rejected2")

    def test_installed_workspace_requires_explicit_path_outside_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.object(workspace, "SOURCE_CHECKOUT", False), patch.object(workspace, "INSTALLATION_ROOT", root):
                with self.assertRaisesRegex(ValueError, "explicit"):
                    workspace.resolve_workspace()
                with self.assertRaisesRegex(ValueError, "installation"):
                    workspace.resolve_workspace(explicit=root)
            with patch.object(workspace, "SOURCE_CHECKOUT", False):
                self.assertEqual(workspace.resolve_workspace(explicit=root).workspace_root, root)


class ArtifactPrivacyTests(unittest.TestCase):
    def test_private_members_in_wheel_or_sdist_are_rejected(self):
        import io
        import tarfile
        import zipfile
        spec = importlib.util.spec_from_file_location("wealth_artifact_test", ROOT / "scripts/check_packages.py")
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        for kind in ("wheel", "sdist"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                plugin = base / "wealth_ledger_synthetic_parser-0.1.0-py3-none-any.whl"
                with zipfile.ZipFile(plugin, "w") as archive:
                    archive.writestr("synthetic_parser/__init__.py", (ROOT / "examples/parser-plugin/src/synthetic_parser/__init__.py").read_bytes())
                    prefix = "wealth_ledger_synthetic_parser-0.1.0.dist-info/"
                    archive.writestr(prefix + "entry_points.txt", b"[wealth_ledger.source_adapters]\nsynthetic=synthetic_parser:register\n")
                    archive.writestr(prefix + "licenses/LICENSE", (ROOT / "LICENSE").read_bytes())
                with zipfile.ZipFile(base / "wealth_ledger-0.1.0-py3-none-any.whl", "w", zipfile.ZIP_DEFLATED) as archive:
                    for name in ("wealth_ledger/source_protocol.py", "wealth_ledger/source_testing.py",
                                 "wealth_ledger/_bundle/assets/fonts/NotoSansTC-Regular.ttf"):
                        archive.writestr(name, (ROOT / audit.public_source(name)).read_bytes())
                    if kind == "wheel":
                        archive.writestr("wealth_ledger/AGENTS.override.md", b"synthetic private instructions")
                with tarfile.open(base / "wealth_ledger-0.1.0.tar.gz", "w:gz") as archive:
                    for name in ("build_backend.py", "scripts/check_publication.py", "assets/fonts/OFL.txt",
                                 "src/wealth_ledger/source_protocol.py", "AGENTS.override.md"):
                        raw = b"synthetic private instructions" if name == "AGENTS.override.md" else (ROOT / name).read_bytes()
                        member = tarfile.TarInfo("wealth_ledger-0.1.0/" + name)
                        member.size = len(raw)
                        archive.addfile(member, io.BytesIO(raw))
                with self.assertRaisesRegex(ValueError, "Unexpected artifact content"):
                    audit.audit_artifacts(base)
