"""Separate immutable installation resources from explicitly selected private state."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

CODE_ROOT = Path(__file__).resolve().parents[2]


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
    root = Path(legacy_root if explicit is None else explicit).expanduser().resolve(strict=True)
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
