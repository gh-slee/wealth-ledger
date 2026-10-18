"""Separate immutable installation resources from explicitly selected private state."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

PACKAGE_ROOT = Path(__file__).resolve().parent
# Source images also use src/ but deliberately omit build metadata.
SOURCE_CHECKOUT = not (PACKAGE_ROOT / "_bundle").exists() and PACKAGE_ROOT.parent.name == "src"
CODE_ROOT = PACKAGE_ROOT.parents[1] if SOURCE_CHECKOUT else PACKAGE_ROOT / "_bundle"
INSTALLATION_ROOT = CODE_ROOT if SOURCE_CHECKOUT else PACKAGE_ROOT.parent


@dataclass(frozen=True)
class Workspace:
    code_root: Path
    workspace_root: Path

    @property
    def database(self) -> Path:
        return self.workspace_root / "data/db/portfolio.sqlite3"

    @property
    def cache(self) -> Path:
        return self.workspace_root / "work/cache"


def resolve_workspace(legacy_root=CODE_ROOT, explicit=None) -> Workspace:
    """Explicit paths must already exist; a typo never falls back to another ledger.

    An empty directory can become a ledger on the first mutation. Nonempty
    directories must contain recognizable ledger state or local configuration.
    Resolution itself never creates files or initializes a database.
    """
    if not SOURCE_CHECKOUT and explicit is None and Path(legacy_root) == CODE_ROOT:
        raise ValueError("Installed core requires an explicit private workspace directory")
    root = Path(legacy_root if explicit is None else explicit).expanduser().resolve(strict=True)
    if not SOURCE_CHECKOUT and root.is_relative_to(INSTALLATION_ROOT):
        raise ValueError("Private workspace must be outside the package installation")
    if not root.is_dir():
        raise ValueError("Workspace must be an existing directory")
    for name in ("data", "data/db", "data/db/portfolio.sqlite3", "work", "config",
                 "config/local.toml", "config/company-aliases.json", "config/company-aliases.override.json",
                 "reports", "backups"):
        if not (root / name).resolve().is_relative_to(root):
            raise ValueError("Workspace state paths must stay within the selected directory")
    if explicit is not None:
        recognizable = any((root / path).is_file() for path in
                           ("data/db/portfolio.sqlite3", "reports/latest.json", "config/local.toml",
                            "config/bull-opening.json", "config/company-aliases.json",
                            "config/company-aliases.override.json"))
        if root != Path(legacy_root).resolve() and any(root.iterdir()) and not recognizable:
            raise ValueError("Workspace is not empty and contains no recognized ledger state/configuration")
        if root == Path(root.anchor) or root == Path.home():
            raise ValueError("Choose a dedicated portfolio directory, not the filesystem root or home")
    return Workspace(CODE_ROOT, root)


def workspace_from_args(legacy_root=CODE_ROOT, argv=None) -> Workspace:
    """Resolve workspace before reading locale/settings, including subcommands."""
    args = list(sys.argv[1:] if argv is None else argv)
    selected = []
    for index, value in enumerate(args):
        if value == "--":
            break
        if value.startswith("--workspace="):
            selected.append(value.split("=", 1)[1])
        elif value == "--workspace":
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                raise ValueError("argument --workspace: expected a directory")
            selected.append(args[index + 1])
    if len(selected) > 1 or selected == [""]:
        raise ValueError("Supply --workspace once with a nonempty directory")
    return resolve_workspace(legacy_root, selected[0] if selected else None)
