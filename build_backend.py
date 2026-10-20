"""PEP 517 hooks: build only an audited, minimal copy, never the live ledger tree.

No editable builds: a source checkout uses PYTHONPATH=src. Packages contain core
code, locale catalogs and reviewed resources, not CLI scripts or the Web UI build.
"""
from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parent
ROOT_FILES = ("pyproject.toml", "build_backend.py", "MANIFEST.in", "README.md", "LICENSE",
              "THIRD_PARTY_NOTICES.md", "scripts/check_publication.py", "config/company-aliases.json")
FONTS = ("NotoSansTC-Regular.ttf", "NotoSansSC-Regular.ttf", "NotoSansSC-provenance.json",
         "OFL.txt", "OFL-SC.txt", "README.md")
LOCALES = ("registry.json", "legacy.json", "en-CA.json", "zh-TW.json", "zh-CN.json")


def _read(root, name):
    path = root / name
    if any(part.is_symlink() for part in (path, *path.parents) if part != root.parent):
        raise ValueError("Build inputs must not contain symlinks")
    if not path.is_file():
        raise ValueError("Required public build input is missing")
    return path.read_bytes()


def stage_source(root, destination):
    """Explicit artifact allowlist, independent of ignored or even staged files."""
    root, destination = Path(root), Path(destination)
    if root.is_symlink():
        raise ValueError("Build root must not be a symlink")
    root = root.resolve(strict=True)
    spec = importlib.util.spec_from_file_location("_wealth_build_audit", root / "scripts/check_publication.py")
    # Check the guard itself before executing any local module.
    _read(root, "scripts/check_publication.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    names = list(ROOT_FILES)
    package = root / "src/wealth_ledger"
    if package.is_symlink():
        raise ValueError("Build package must not be a symlink")
    for path in package.rglob("*"):
        if path.is_symlink():
            raise ValueError("Build package must not contain symlinks")
        if path.suffix == ".py" and "__pycache__" not in path.parts:
            names.append(path.relative_to(root).as_posix())
    names += ["assets/fonts/" + name for name in FONTS]
    names += ["src/wealth_ledger/locales/" + name for name in LOCALES]
    for name in sorted(set(names)):
        raw = _read(root, name)
        if not guard.path_allowed(name) or guard.content_issues(raw, name):
            raise ValueError("Public build input failed publication audit: " + name)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    bundle = destination / "src/wealth_ledger/_bundle"
    shutil.copytree(destination / "assets", bundle / "assets")
    (bundle / "config").mkdir()
    shutil.copyfile(destination / "config/company-aliases.json", bundle / "config/company-aliases.json")


@contextmanager
def _build_tree():
    from setuptools import build_meta
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="wealth-ledger-public-build-") as temporary:
        staged = Path(temporary)
        stage_source(ROOT, staged)
        try:
            os.chdir(staged)
            yield build_meta
        finally:
            os.chdir(previous)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    output = str(Path(wheel_directory).resolve())
    metadata = str(Path(metadata_directory).resolve()) if metadata_directory else None
    with _build_tree() as backend:
        return backend.build_wheel(output, config_settings, metadata)


def build_sdist(sdist_directory, config_settings=None):
    output = str(Path(sdist_directory).resolve())
    with _build_tree() as backend:
        return backend.build_sdist(output, config_settings)


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    output = str(Path(metadata_directory).resolve())
    with _build_tree() as backend:
        return backend.prepare_metadata_for_build_wheel(output, config_settings)


def get_requires_for_build_wheel(config_settings=None):
    return []


def get_requires_for_build_sdist(config_settings=None):
    return []
