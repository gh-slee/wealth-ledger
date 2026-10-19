#!/usr/bin/env python3
"""Audit local core artifacts and verify an independently installed synthetic SDK.

Run after building core/plugin and installing their wheels into a disposable venv
with requirements-web-test.lock. Never run this against a user's application venv.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("_package_audit", ROOT / "scripts/check_publication.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
FONT_NAMES = {"NotoSansTC-Regular.ttf", "NotoSansSC-Regular.ttf", "NotoSansSC-provenance.json",
              "OFL.txt", "OFL-SC.txt", "README.md"}
CATALOG_NAMES = {"registry.json", "legacy.json", "en-CA.json", "zh-TW.json", "zh-CN.json"}
META_NAMES = {"METADATA", "WHEEL", "RECORD", "entry_points.txt", "top_level.txt",
              "licenses/LICENSE", "licenses/THIRD_PARTY_NOTICES.md"}
EGG_NAMES = {"PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "requires.txt", "top_level.txt"}


def public_source(name):
    if name.startswith("wealth_ledger/"):
        name = "src/" + name
    bundle = "src/wealth_ledger/_bundle/"
    if name.startswith(bundle):
        name = name[len(bundle):]
    allowed = (name.startswith("src/wealth_ledger/") and name.endswith(".py")
               or name.startswith("src/wealth_ledger/locales/") and name.rsplit("/", 1)[-1] in CATALOG_NAMES
               or name.startswith("assets/fonts/") and name.rsplit("/", 1)[-1] in FONT_NAMES
               or name == "config/company-aliases.json")
    return name if allowed and guard.path_allowed(name) else None


def audit_artifacts(directory):
    wheel, = directory.glob("wealth_ledger-*.whl")
    sdist, = directory.glob("wealth_ledger-*.tar.gz")
    plugin, = directory.glob("wealth_ledger_synthetic_parser-*.whl")
    with zipfile.ZipFile(plugin) as archive:
        seen = set()
        for item in archive.infolist():
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("Symlink example wheel member")
            name, raw = item.filename, archive.read(item)
            if name in seen:
                raise ValueError("Duplicate example wheel member")
            seen.add(name)
            if name == "synthetic_parser/__init__.py":
                source = "examples/parser-plugin/src/" + name
                if raw != (ROOT / source).read_bytes() or guard.content_issues(raw, source):
                    raise ValueError("Example wheel differs from reviewed source")
            elif name.startswith("wealth_ledger_synthetic_parser-0.1.0.dist-info/"):
                tail = name.split(".dist-info/", 1)[1]
                if tail not in META_NAMES or tail == "licenses/THIRD_PARTY_NOTICES.md" or guard.content_issues(raw, name):
                    raise ValueError("Unexpected example wheel metadata")
            else:
                raise ValueError("Unexpected example wheel member")
        if not {"synthetic_parser/__init__.py", "wealth_ledger_synthetic_parser-0.1.0.dist-info/entry_points.txt",
                "wealth_ledger_synthetic_parser-0.1.0.dist-info/licenses/LICENSE"} <= seen:
            raise ValueError("Example wheel lacks required source/license/registration")
    counts = {plugin.name: len(seen)}
    for path in (wheel, sdist):
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as archive:
                if any(stat.S_ISLNK(item.external_attr >> 16) for item in archive.infolist()):
                    raise ValueError("Symlink wheel member")
                entries = [(item.filename, archive.read(item)) for item in archive.infolist()]
        else:
            with tarfile.open(path) as archive:
                members = archive.getmembers()
                if any(not (item.isdir() or item.isfile()) for item in members):
                    raise ValueError("Nonregular sdist member")
                prefixes = {PurePosixPath(item.name).parts[0] for item in members}
                if len(prefixes) != 1:
                    raise ValueError("Unexpected sdist roots")
                entries = [(str(PurePosixPath(item.name).relative_to(next(iter(prefixes)))), archive.extractfile(item).read())
                           for item in members if item.isfile()]
        seen = set()
        for name, raw in entries:
            if name in seen or not name or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or "\\" in name:
                raise ValueError("Unsafe or duplicate artifact member")
            seen.add(name)
            source = public_source(name)
            if source:
                if raw != (ROOT / source).read_bytes() or guard.content_issues(raw, source):
                    raise ValueError("Artifact differs from reviewed public source: " + source)
                continue
            if path.suffix == ".whl":
                prefix, separator, tail = name.partition(".dist-info/")
                allowed = separator and prefix.startswith("wealth_ledger-") and "/" not in prefix and tail in META_NAMES
            else:
                allowed = name in {"pyproject.toml", "build_backend.py", "MANIFEST.in", "README.md", "LICENSE",
                                   "THIRD_PARTY_NOTICES.md", "scripts/check_publication.py"}
                if allowed:
                    allowed = raw == (ROOT / name).read_bytes()
                allowed = allowed or (name == "setup.cfg" and raw == b"[egg_info]\ntag_build = \ntag_date = 0\n\n") or name == "PKG-INFO" or (name.startswith("src/wealth_ledger.egg-info/")
                    and name.rsplit("/", 1)[-1] in EGG_NAMES and len(PurePosixPath(name).parts) == 3)
            if not allowed or guard.content_issues(raw, name):
                raise ValueError("Unexpected artifact content: " + name)
        required = {"wealth_ledger/source_protocol.py", "wealth_ledger/source_testing.py",
                    "wealth_ledger/_bundle/assets/fonts/NotoSansTC-Regular.ttf"} if path.suffix == ".whl" else {
                    "build_backend.py", "scripts/check_publication.py", "assets/fonts/OFL.txt", "src/wealth_ledger/source_protocol.py"}
        if not required <= seen:
            raise ValueError("Artifact lacks required public resources")
        counts[path.name] = len(seen)
    return counts


def run(command, cwd, env, *, test_count=None):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
    if result.returncode:
        # Test evidence is synthetic, but avoid dumping installation paths by default.
        raise RuntimeError("Package acceptance failed: " + result.stderr[-4000:])
    if test_count is not None and (not re.search(r"Ran " + str(test_count) + r" tests?\b", result.stderr) or "skipped=" in result.stderr):
        raise RuntimeError("Installed acceptance did not execute the expected test set")
    return result.stdout


def verify_installed(python):
    python = Path(python).absolute()  # Preserve the venv executable, not its resolved base Python.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "MPLBACKEND": "Agg"}
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    with tempfile.TemporaryDirectory(prefix="wealth-ledger-sdk-acceptance-") as temporary:
        base = Path(temporary)
        check = '''
import json
from pathlib import Path
import wealth_ledger
from wealth_ledger.workspace import PACKAGE_ROOT, CODE_ROOT, SOURCE_CHECKOUT, resolve_workspace
from wealth_ledger.resources import company_aliases
from wealth_ledger.source_registry import AdapterRegistration
from synthetic_parser import register
assert not SOURCE_CHECKOUT
assert PACKAGE_ROOT.parent.name in {"site-packages", "dist-packages"}
assert isinstance(register(), AdapterRegistration)
assert company_aliases(Path.cwd())[0]["version"] == 2
assert (CODE_ROOT / "assets/fonts/NotoSansTC-Regular.ttf").is_file()
try:
    resolve_workspace()
except ValueError:
    pass
else:
    raise AssertionError("Installed default workspace must be rejected")
print(json.dumps({"package": str(PACKAGE_ROOT)}))
'''
        location = json.loads(run([str(python), "-I", "-c", check], base, env))["package"]
        if Path(location).resolve().is_relative_to(ROOT / "src"):
            raise ValueError("Acceptance imported the source checkout")
        tests = base / "plugin-tests"
        shutil.copytree(ROOT / "examples/parser-plugin/tests", tests, ignore=shutil.ignore_patterns("__pycache__"))
        run([str(python), "-I", "-m", "unittest", "discover", "-s", str(tests), "-v"], base, env, test_count=7)
        raw = run([str(python), "-I", "-c", f"import sys; sys.path.insert(0, {str(tests)!r}); from test_synthetic_parser import fixture; print(fixture().decode(), end='')"], base, env)
        source = base / "synthetic.csv"; source.write_text(raw, encoding="utf-8")
        config = base / "parsers.json"
        config.write_text(json.dumps({"schema_version": 1, "enabled": [{"distribution":"wealth-ledger-synthetic-parser",
            "version":"0.1.0", "entry_point":"synthetic", "adapter_id":"synthetic.holdings"}], "bindings": []}))
        console = python.parent / ("wealth-ledger-source-parsers.exe" if os.name == "nt" else "wealth-ledger-source-parsers")
        command = [str(console), str(source), "--config", str(config)]
        submission_console=python.parent / ("wealth-ledger-source-ingestion.exe" if os.name=="nt" else "wealth-ledger-source-ingestion")
        run([str(submission_console),"--help"],base,env)
        plan = json.loads(run(command, base, env))
        assert plan["ingestible"] is False and plan["booking_blocker"] == "protocol_v1_not_bookable"
        assert plan["inputs"][0]["record_counts"] == {"holdings": 1}
        assert "demo-account" not in json.dumps(plan)
        receipt = base / "receipt.json"; receipt.write_text(json.dumps(plan))
        assert json.loads(run(command + ["--verify", str(receipt)], base, env))["fingerprint"] == plan["fingerprint"]
        assert not list(base.rglob("*.sqlite3"))
        # Copy only reviewed demo resources. No source package or Web bundle is copied.
        demo = base / "demo"; (demo / "examples").mkdir(parents=True)
        shutil.copyfile(ROOT / "examples/demo.py", demo / "examples/demo.py")
        (demo / "examples/data").mkdir()
        for name in ("wealthsimple-holdings.csv", "bull-orders.csv", "fx.json", "btc-price.json"):
            shutil.copyfile(ROOT / "examples/data" / name, demo / "examples/data" / name)
        (demo / "config").mkdir()
        for name in ("company-aliases.json", "bull-opening.example.json"):
            shutil.copyfile(ROOT / "config" / name, demo / "config" / name)
        canonical = base / "canonical"; (canonical / "tests").mkdir(parents=True)
        for name in ("test_source_v2.py", "test_source_ingestion.py", "test_source_builtin.py", "test_source_context_pipeline.py", "test_source_submission.py", "test_source_projection.py", "test_source_legacy_projection.py"):
            shutil.copyfile(ROOT / "tests" / name, canonical / "tests" / name)
        (canonical / "examples/data").mkdir(parents=True)
        for name in ("wealthsimple-holdings.csv", "bull-orders.csv", "fx.json"):
            shutil.copyfile(ROOT / "examples/data" / name, canonical / "examples/data" / name)
        run([str(python), "-I", "-m", "unittest", "discover", "-s", str(canonical / "tests"), "-v"],base,env,test_count=148)
        for locale in ("en-CA", "zh-TW", "zh-CN"):
            run([str(python), "-I", str(demo / "examples/demo.py"), "--output", str(base / locale), "--locale", locale], base, env)
    return {"installed_outside_checkout": True, "plugin_tests": 7, "canonical_ingestion_tests": 35, "context_parser_tests": 29, "source_submission_tests": 22, "source_projection_tests": 29, "source_legacy_projection_tests": 33, "plan_and_revalidation": True,
            "report_locales": ["en-CA", "zh-TW", "zh-CN"], "financial_booking": False,
            "financial_booking_scope": "v1_nonbooking_source_plan",
            "synthetic_canonical_submission": True, "real_financial_data_used": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True, help="Disposable venv with installed core/plugin wheels and test dependencies")
    args = parser.parse_args()
    print(json.dumps({"archives": audit_artifacts(args.artifacts.resolve()), "acceptance": verify_installed(args.python)}, indent=2))


if __name__ == "__main__":
    main()
