"""Bounded offline code/dependency fingerprints for isolated parser previews."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import sysconfig

MAX_CODE_BYTES = 1024 * 1024 * 1024
MAX_CODE_FILES = 50000


class EnvironmentError(ValueError):
    """An environment could not be completely fingerprinted within its bounds."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def environment_fingerprint(*, roots=None, executable=None):
    """Hash actual installed code/data, not only package versions or RECORD claims.

    Runtime roots are code-only locations, never a portfolio. Isolated execution
    uses an empty bytecode prefix and disables writes, so caches are excluded.
    Injectable roots/executable support small, independently authored test fixtures.
    """
    from .workspace import PACKAGE_ROOT
    if roots is None:
        roots = {"core": PACKAGE_ROOT, "stdlib": Path(sysconfig.get_path("stdlib"))}
        sites = sorted({sysconfig.get_path("purelib"), sysconfig.get_path("platlib")})
        roots.update({"site-" + str(index): Path(path) for index, path in enumerate(sites)})
    total, count, evidence = 0, 0, []

    def read(path):
        nonlocal total, count
        size = path.stat().st_size
        count += 1
        total += size
        if total > MAX_CODE_BYTES or count > MAX_CODE_FILES:
            raise EnvironmentError("Source environment exceeds fingerprint limits")
        value = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(block)
        if path.stat().st_size != size:
            raise EnvironmentError("Source environment changed during inspection")
        return [size, value.hexdigest()]

    try:
        for label, base in sorted(roots.items()):
            base = Path(base).resolve(strict=True)
            if not base.is_dir():
                raise EnvironmentError("Source environment root is unavailable")
            def walk_error(error):
                raise EnvironmentError("Source environment could not be completely enumerated")
            for directory, dirs, names in os.walk(base, followlinks=False, onerror=walk_error):
                # The standard library can contain site packages handled separately.
                dirs[:] = sorted(name for name in dirs if name != "__pycache__" and not (label == "stdlib" and name in {"site-packages", "dist-packages"}))
                for name in dirs:
                    if (Path(directory) / name).is_symlink():
                        raise EnvironmentError("Source environment contains a directory symlink")
                for name in sorted(names):
                    path = Path(directory) / name
                    relative = path.relative_to(base).as_posix()
                    if path.suffix in {".pyc", ".pyo"} or name == ".DS_Store":
                        continue
                    if label == "core" and path.suffix not in {".py", ".json"}:
                        continue
                    resolved = path.resolve(strict=True)
                    runtime_link = (label == "stdlib" and name.startswith("libpython")
                                    and resolved.is_relative_to(Path(sys.base_prefix).resolve()))
                    if not resolved.is_relative_to(base) and not runtime_link:
                        raise EnvironmentError("Source environment file escapes its root")
                    if path.suffix == ".pth":
                        # External/editable roots and startup code cannot be attested
                        # by scanning only the declared isolated environment.
                        for line in path.read_text(encoding="utf-8").splitlines():
                            if line.strip() and not line.lstrip().startswith("#"):
                                raise EnvironmentError("Executable or external path hooks are unsupported")
                    evidence.append([label, relative, *read(path)])
        binary = Path(executable or sys.executable).resolve(strict=True)
        evidence.append(["runtime", platform.python_implementation(), sys.version, platform.machine(), *read(binary)])
        return digest(evidence)
    except EnvironmentError:
        raise
    except (OSError, ValueError, UnicodeError):
        raise EnvironmentError("Source environment could not be verified") from None
