#!/usr/bin/env python3
"""Verify a reviewed example wheel in a disposable derived source Docker image.

The supplied local base image is never modified/deleted. Only a uniquely named test
image and temporary build directory are created; no financial volume is attached.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def verify(base_image, wheel):
    image = "wealth-ledger-sdk-test-" + uuid.uuid4().hex + ":derived"
    if wheel.name != "wealth_ledger_synthetic_parser-0.1.0-py3-none-any.whl":
        raise ValueError("Supply the reviewed synthetic example wheel")
    try:
        with tempfile.TemporaryDirectory(prefix="wealth-ledger-plugin-image-") as directory:
            context = Path(directory)
            shutil.copyfile(wheel, context / wheel.name)
            (context / "Dockerfile").write_text('''ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY *.whl /tmp/
RUN python -m pip install --no-index --no-deps --no-cache-dir --no-compile /tmp/*.whl
USER 10001:10001
''')
            subprocess.run(["docker", "build", "--build-arg", "BASE_IMAGE=" + base_image, "--tag", image, str(context)], check=True)
        tests = {name: (ROOT / "examples/parser-plugin/tests" / name).read_text()
                 for name in ("test_synthetic_parser.py", "test_installed_api.py")}
        code = '''import json, os, pathlib, sys, tempfile, unittest
assert os.getuid() == 10001
assert not pathlib.Path('/app/AGENTS.override.md').exists()
from wealth_ledger.workspace import CODE_ROOT, SOURCE_CHECKOUT
assert SOURCE_CHECKOUT and CODE_ROOT == pathlib.Path('/app')
with tempfile.TemporaryDirectory() as directory:
    for name, content in json.loads(sys.stdin.read()).items():
        pathlib.Path(directory, name).write_text(content)
    sys.path.insert(0, directory)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(directory))
    assert result.testsRun == 7 and not result.skipped
    if not result.wasSuccessful():
        raise SystemExit(1)
'''
        subprocess.run(["docker", "run", "--rm", "-i", "--read-only", "--network=none", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--pids-limit=256", "--memory=1g",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,uid=10001,gid=10001,mode=0700",
            "--entrypoint", "python", image, "-c", code], input=json.dumps(tests), text=True, check=True)
    finally:
        subprocess.run(["docker", "image", "rm", image], capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-image", required=True, help="Reviewed local source image; never a user's running instance")
    parser.add_argument("--wheel", required=True, type=Path)
    args = parser.parse_args()
    verify(args.base_image, args.wheel)
    print(json.dumps({"derived_image_tests":7, "financial_volume_attached":False, "network_enabled":False}))


if __name__ == "__main__":
    main()
