#!/usr/bin/env python3
"""Inventory locked dependency versions and upstream license metadata, offline."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_python(root, name, seen=None):
    seen = set() if seen is None else seen
    if name in seen or name not in {"requirements.lock", "requirements-web.lock", "requirements-web-test.lock"}:
        raise ValueError("Invalid or cyclic dependency lock")
    seen.add(name)
    packages = {}
    for raw in (root / name).read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            values = locked_python(root, line[3:].strip(), seen)
        else:
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9.+!-]+)", line)
            if not match:
                raise ValueError("Dependency inventory requires exact version pins")
            values = {normalized(match[1]): match[2]}
        for package, version in values.items():
            if package in packages and packages[package] != version:
                raise ValueError("Conflicting dependency version pins")
            packages[package] = version
    return packages


def python_inventory(root, lock, distribution=importlib.metadata.distribution):
    rows = []
    for name, version in sorted(locked_python(root, lock).items()):
        installed = distribution(name)
        if installed.version != version:
            raise ValueError("Installed Python version differs from lock: " + name)
        metadata = installed.metadata
        expression = metadata.get("License-Expression")
        legacy = metadata.get("License")
        classifiers = [value for value in metadata.get_all("Classifier", []) if value.startswith("License ::")]
        evidence = []
        for path in installed.files or []:
            if any(part.endswith(".dist-info") for part in path.parts) and path.name.lower().startswith(("license", "copying", "notice")):
                raw = path.locate().read_bytes()
                if raw:
                    evidence.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
        # Values are upstream declarations, not inferred SPDX identifiers or legal clearance.
        rows.append({"name": name, "version": version, "license_expression": expression,
                     "license_metadata": legacy, "license_classifiers": classifiers,
                     "license_files": metadata.get_all("License-File", []), "license_evidence": evidence,
                     "license_declared": bool(expression or legacy and legacy.strip().lower() not in {"unknown", "none"}
                                              or classifiers or evidence)})
    return rows


def npm_inventory(root):
    lock = json.loads((root / "frontend/package-lock.json").read_text())
    if lock.get("lockfileVersion") != 3:
        raise ValueError("Unsupported npm lock format")
    rows = []
    for location, package in sorted(lock["packages"].items()):
        if not location:
            continue
        if not location.startswith("node_modules/") or ".." in Path(location).parts:
            raise ValueError("Unexpected npm package location")
        name = package.get("name") or location.rsplit("node_modules/", 1)[1]
        license_value = package.get("license")
        rows.append({"name": name, "version": package["version"], "location": location,
                     "development_only": bool(package.get("dev")), "optional": bool(package.get("optional")),
                     "platform_os": package.get("os", []), "platform_cpu": package.get("cpu", []),
                     "license_metadata": license_value, "license_declared": bool(license_value),
                     "integrity": package.get("integrity")})
    return rows


def inventory(root=ROOT, lock="requirements-web.lock", distribution=importlib.metadata.distribution):
    python_rows = python_inventory(root, lock, distribution)
    npm_rows = npm_inventory(root)
    notices = ("LICENSE", "THIRD_PARTY_NOTICES.md", "assets/fonts/OFL.txt", "assets/fonts/OFL-SC.txt",
               "frontend/public/licenses/atkinson-hyperlegible.txt",
               "frontend/public/licenses/ibm-plex-sans-condensed.txt", "frontend/public/licenses/shadcn-ui.txt")
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in notices}
    unknown = [{"ecosystem": kind, "name": row["name"], "version": row["version"]}
               for kind, rows in (("python", python_rows), ("npm", npm_rows))
               for row in rows if not row["license_declared"]]
    return {"format": "wealth-ledger-dependency-inventory", "version": 1, "python_lock": lock,
            "scope": "Installed locked Python distributions; all npm lock entries including optional platform/build tools; bundled notices",
            "limitations": "Upstream license declarations, not legal approval, vulnerability scanning or a complete OS/image SBOM. Retain upstream license files.",
            "python": python_rows, "npm": npm_rows, "bundled_notice_sha256": hashes, "undeclared": unknown}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-lock", choices=("requirements.lock", "requirements-web.lock", "requirements-web-test.lock"),
                        default="requirements-web.lock")
    parser.add_argument("--require-declared", action="store_true", help="Fail on absent upstream license declarations")
    parser.add_argument("--output", type=Path, help="New JSON file; otherwise stdout. No network or workspace access")
    args = parser.parse_args()
    try:
        result = inventory(lock=args.python_lock)
        if args.require_declared and result["undeclared"]:
            raise ValueError("Dependencies without a license declaration need review")
        encoded = json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
        if args.output:
            with args.output.open("x") as stream:
                stream.write(encoded)
        else:
            print(encoded, end="")
    except (ValueError, OSError, KeyError, importlib.metadata.PackageNotFoundError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
