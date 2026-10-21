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
        # Two report editions at one cutoff are not two financial observations.
        with store.transaction() as conn:
            old = jobs._insert(conn, portfolio["id"], "update", {}, uuid.uuid4().hex, "synthetic-earlier-edition")
        for artifact in output.rglob("*"):
            if artifact.is_file() and artifact.suffix in (".md", ".pdf", ".ods", ".json", ".csv", ".png"):
                store.register_artifact(portfolio["id"], old["id"], artifact.relative_to(project).as_posix())
        jobs.state(old["id"], "published", result={"valuation_as_of":payload["meta"]["as_of"]})
        with store.transaction() as conn:
            conn.execute("UPDATE jobs SET updated_at=updated_at-60 WHERE id=?", (old["id"],))
        # Independent old-format declaration; all bytes originate in the synthetic demo.
        import shutil
        from wealth_ledger.core import import_holdings
        from wealth_ledger.crypto import import_bull_orders
        from wealth_ledger.combined import make_combined_payload
        from wealth_ledger.web.adoption import prepare_adoption, confirm_adoption
        legacy = Path(temporary) / "legacy-cli"
        data = ROOT / "examples/data"
        fx = json.loads((data / "fx.json").read_text())
        import_holdings(legacy, data / "wealthsimple-holdings.csv", "baseline", fx)
        import_bull_orders(legacy, data / "bull-orders.csv", opening_assumption=json.loads((ROOT / "config/bull-opening.example.json").read_text()))
        make_combined_payload(legacy, as_of=payload["meta"]["as_of"], price_file=data / "btc-price.json", fx=fx)
        folder = legacy / "reports/legacy"
        shutil.copytree(output, folder, ignore=shutil.ignore_patterns("*.txt"))
        (folder / "manifest.json").write_text(json.dumps({
            "snapshot_id": payload["meta"]["snapshot_id"], "snapshot_as_of": payload["meta"]["as_of"],
            "report_generated_at": "2024-02-02T12:00:00-05:00", "import": {},
            "workbook_validation": {"generator": "python_odf_direct"}, "database_backup": None,
            "reporting": {"markdown": "report.md", "pdf": "report.pdf"}}))
        (legacy / "reports/latest.json").write_text(json.dumps({"path":"reports/legacy", "snapshot_id":payload["meta"]["snapshot_id"]}))
        plan = Path(temporary) / "private-legacy-plan.json"
        preview = prepare_adoption(settings,legacy,"Legacy synthetic portfolio",plan,allow_legacy_reports=True)
        confirm_adoption(settings,plan,preview["plan_sha256"])
        # A real source-report operation/registry, with invented direct instruments.
        from wealth_ledger.web.source_reports import enqueue_preview, confirm_preview
        from wealth_ledger.web.worker import execute_job
        from wealth_ledger.web.uploads import upload_path
        from wealth_ledger.source_context_pipeline import context_document
        from wealth_ledger.source_builtin import WealthsimpleHoldings, WS_FORMAT
        from wealth_ledger.source_v2 import ParseContext
        from wealth_ledger.prices import parse_time
        from datetime import datetime, timezone
        source_portfolio = store.create_portfolio("Source synthetic portfolio", "en-CA", "actual_only")
        source_pid = source_portfolio["id"]
        raw = (data / "wealthsimple-holdings.csv").read_bytes().replace(b"VEQT", b"DEMO-ETF").replace(b"QQQ", b"DEMO-ETF-US")
        upload_id = uuid.uuid4().hex
        upload = {"id":upload_id,"portfolio_id":source_pid,"kind":"source_csv"}
        source_path = upload_path(store, upload); source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(raw)
        with store.transaction() as conn:
            conn.execute("INSERT INTO uploads(id,portfolio_id,kind,provider,original_name,sha256,byte_size,created_at) VALUES(?,?,'source_csv',NULL,'synthetic.csv',?,?,?)",
                         (upload_id,source_pid,hashlib.sha256(raw).hexdigest(),len(raw),store.clock()))
        context = ParseContext(parse_time(payload["meta"]["as_of"]), "synthetic-browser-source", source_timezone="America/Toronto")
        batch = WealthsimpleHoldings().normalize(raw, export_version=WS_FORMAT, context=context)
        request = {"upload_ids":[upload_id],"contexts":context_document((context,))["inputs"],
                   "bindings":[{"provider":a.key.provider,"source_account_id":a.key.account_id,"target_kind":"new"} for a in batch.accounts],"selections":{},
                   "valuation":{"as_of":payload["meta"]["as_of"],"period_start":"2023-12-31T00:00:00Z","generated_at":datetime.now(timezone.utc).isoformat(),"fx":fx,"report_locale":"en-CA"}}
        source_preview = enqueue_preview(store,source_pid,request,uuid.uuid4().hex)
        execute_job(settings,source_preview["id"])
        source_preview = jobs.get(source_pid,source_preview["id"])
        assert source_preview["status"] == "ready"
        approval = json.loads(source_preview["result_json"])["approval_sha256"]
        source_job = confirm_preview(store,source_pid,{"preview_id":source_preview["id"],"approval_sha256":approval},uuid.uuid4().hex)
        execute_job(settings,source_job["id"])
        assert jobs.get(source_pid,source_job["id"])["status"] == "published"
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
