#!/usr/bin/env python3
"""Disposable browser-test server with synthetic reports; never uses owner state."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def main():
    import uvicorn
    from examples.demo import run_demo
    from wealth_ledger.web.api import create_app
    from wealth_ledger.web.auth import password_hash
    from wealth_ledger.web.config import WebSettings
    from wealth_ledger.web.jobs import Jobs
    from wealth_ledger.web.storage import Store, prepare_instance
    import json
    import hashlib
    with tempfile.TemporaryDirectory(prefix="wealth-browser-synthetic-") as temporary:
        settings = WebSettings(Path(temporary) / "instance", "http://localhost:8765")
        prepare_instance(settings)
        store = Store(settings)
        store.set_owner("example-owner", password_hash("example-browser-only-password"))
        portfolio = store.create_portfolio("SYNTHETIC demonstration", "en-CA", "actual_only")
        store.create_portfolio("Empty synthetic portfolio", "en-CA", "actual_only")
        _, project = store.portfolio(portfolio["id"])
        output = project / "reports/synthetic"
        run_demo(output, "actual_only")
        payload = json.loads((output / "data.json").read_text())
        jobs = Jobs(store)
        with store.transaction() as conn:
            row = jobs._insert(conn, portfolio["id"], "update", {}, uuid.uuid4().hex, "synthetic-browser-fixture")
        bundle_files = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in output.rglob("*") if p.is_file() and p.suffix in (".md", ".pdf", ".ods", ".json", ".csv", ".png")}
        (output / "manifest.json").write_text(json.dumps({"synthetic":True,
            "import":{"operation_id":row["core_operation_id"]}, "bundle_files":bundle_files,
            "data_sha256":bundle_files["data.json"]}))
        for path in output.rglob("*"):
            if path.is_file() and path.suffix in (".md", ".pdf", ".ods", ".json", ".csv", ".png"):
                store.register_artifact(portfolio["id"], row["id"], path.relative_to(project).as_posix())
        jobs.state(row["id"], "published", result={"valuation_as_of":payload["meta"]["as_of"]})
        environment = {**os.environ, "WEALTH_LEDGER_DATA_ROOT":str(settings.data_root),
                       "WEALTH_LEDGER_PUBLIC_ORIGIN":settings.public_origin, "PYTHONDONTWRITEBYTECODE":"1"}
        worker = subprocess.Popen([sys.executable, str(ROOT / "scripts/web.py"), "worker"], env=environment)
        try:
            uvicorn.run(create_app(settings), host="127.0.0.1", port=8765, access_log=False, server_header=False)
        finally:
            worker.terminate()
            try:
                worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill(); worker.wait()


if __name__ == "__main__":
    main()
