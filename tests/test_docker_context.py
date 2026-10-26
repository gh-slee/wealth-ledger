"""Image input privacy checks use invented files and a disposable code tree."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from docker_context import FIXED, prepare_context
from check_publication import PUBLIC_ROLE_SKILLS


class DockerContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "code"; self.root.mkdir()
        for name in FIXED:
            target = self.root / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        source = self.root / "src/wealth_ledger"; source.mkdir(parents=True)
        (source / "__init__.py").write_text('"""Synthetic code only."""\n')

    def test_explicit_context_excludes_financial_state_and_private_instructions(self):
        for name in ("data/source.csv", "reports/report.md", "private/notes.md", "config/local.toml",
                     "AGENTS.override.md", "src/wealth_ledger/AGENTS.override.md", ".env"):
            target = self.root / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("invented private test marker")
        for name in PUBLIC_ROLE_SKILLS:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("invented private test marker")
        output = self.base / "context"
        manifest = prepare_context(self.root, output)
        self.assertFalse((output / ".agents").exists())
        self.assertFalse(set(manifest["files"]) & PUBLIC_ROLE_SKILLS)
        self.assertEqual(set(manifest["files"]), set(FIXED) | {"src/wealth_ledger/__init__.py"})
        for path in output.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"invented private test marker", path.read_bytes())
        with self.assertRaises(ValueError):
            prepare_context(self.root, output)
        with self.assertRaises(ValueError):
            prepare_context(self.root, self.root / "src/context")

    def test_source_credential_failure_does_not_create_context(self):
        (self.root / "src/wealth_ledger/private_code.py").write_text('password = "never-use-this-synthetic-value"\n')
        target = self.base / "rejected-context"
        with self.assertRaisesRegex(ValueError, "publication"):
            prepare_context(self.root, target)
        self.assertFalse(target.exists())

    def test_dockerfile_copies_no_workspace_or_broad_checkout(self):
        text = (ROOT / "Dockerfile").read_text()
        lines = [line for line in text.splitlines() if line.startswith("COPY ")]
        self.assertFalse(any(line.startswith(("COPY . ", "COPY ./ ")) for line in lines))
        self.assertTrue(all(not any(s in line for s in ("data/", "private/", "reports/", ".git/", "local.toml")) for line in lines))
        self.assertIn("USER 10001:10001", text)
        self.assertIn("ARG WEALTH_LEDGER_POSTGRES=0", text)
        self.assertIn("requirements-pg.lock", text)
        self.assertIn("@sha256:", text.splitlines()[0])
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("context: ${WEALTH_LEDGER_BUILD_CONTEXT:-./work/docker-context}", compose)
        self.assertIn('"127.0.0.1:8000:8000"', compose)
        self.assertIn("read_only: true", compose)
        self.assertNotIn("docker.sock", compose)


if __name__ == "__main__":
    unittest.main()
