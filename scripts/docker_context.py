#!/usr/bin/env python3
"""Prepare a minimal audited image context, excluding every private workspace."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

from check_publication import path_allowed, content_issues

CODE_ROOT = Path(__file__).resolve().parents[1]
FIXED = ("Dockerfile", ".dockerignore", "requirements.lock", "requirements-web.lock", "LICENSE",
         "THIRD_PARTY_NOTICES.md", "scripts/web.py", "config/company-aliases.json",
         "assets/fonts/NotoSansTC-Regular.ttf", "assets/fonts/NotoSansSC-Regular.ttf",
         "assets/fonts/NotoSansSC-provenance.json", "assets/fonts/OFL.txt", "assets/fonts/OFL-SC.txt",
         "frontend/package.json", "frontend/package-lock.json", "frontend/tsconfig.json",
         "frontend/vite.config.ts", "frontend/index.html",
         "frontend/public/licenses/ibm-plex-sans-condensed.txt",
         "frontend/public/licenses/atkinson-hyperlegible.txt", "frontend/public/licenses/shadcn-ui.txt")


def prepare_context(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Choose a new context directory; existing paths are never overwritten")
    if output.is_relative_to(root) and not output.is_relative_to(root / "work"):
        raise ValueError("In-checkout Docker contexts must be under ignored work/")
    names = list(FIXED)
    for path in sorted((root / "src/wealth_ledger").rglob("*")):
        relative = path.relative_to(root).as_posix()
        if "__pycache__" not in path.parts and (path.suffix == ".py" or
                path.parent == root / "src/wealth_ledger/locales" and path.suffix == ".json"):
            names.append(relative)
    for path in sorted((root / "frontend/src").rglob("*")):
        if path.suffix in {".ts", ".tsx", ".css", ".json"} and path_allowed(path.relative_to(root).as_posix()):
            names.append(path.relative_to(root).as_posix())
    files = {}
    for name in names:
        path = root / name
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and p.is_relative_to(root)):
            raise ValueError("Symlinks are not permitted in image inputs")
        if not path_allowed(name):
            raise ValueError("Unexpected image input: " + name)
        raw = path.read_bytes()
        if content_issues(raw, name):
            raise ValueError("Image source failed publication inspection: " + name)
        files[name] = raw
    output.mkdir(parents=True)
    try:
        for name, raw in files.items():
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        manifest = {"schema_version": 1, "files": {name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()},
                    "scope": "Explicit code, locked dependencies, bundled fonts/aliases and licenses; no financial workspace"}
        (output / "context-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return manifest
    except BaseException:
        shutil.rmtree(output)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=CODE_ROOT / "work/docker-context")
    args = parser.parse_args()
    try:
        result = prepare_context(CODE_ROOT, args.output)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({"files": len(result["files"]), "output": str(args.output), "private_data_included": False}))


if __name__ == "__main__":
    main()
