"""Isolated job execution and evidence-based recovery; no financial work in HTTP."""
from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from ..application import ApplicationService
from ..locking import file_lock, LockBusy
from ..operations import input_fingerprint, project_lock
from ..workspace import PACKAGE_ROOT, resolve_workspace
from .config import WebSettings
from .jobs import Jobs
from .storage import Store, WebError, contained


def job_guard(store, job_id):
    return file_lock(contained(store.root, "admin/job-" + job_id + ".guard"))


def safe_preview(value, project, uploads_root):
    """Financial preview is owner-only; host/temporary paths are never API fields."""
    if isinstance(value, dict):
        return {key: ("Input validation failed; inspect the source or trusted host diagnostics" if key == "detail"
                      else safe_preview(item, project, uploads_root)) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_preview(item, project, uploads_root) for item in value]
    if isinstance(value, str):
        return value.replace(str(project), "[portfolio]").replace(str(uploads_root), "[uploads]")
    return value


def publish_registry(store, jobs, row, service, saved):
    from ..publishing import verify_bundle
    output = saved.get("output") or {}
    target = Path(output.get("output", ""))
    from .backups import restored_report_path
    target = restored_report_path(store, row["portfolio_id"], target)
    manifest = verify_bundle(service.root, target, row["core_operation_id"])
    names = sorted(manifest["bundle_files"]) + ["manifest.json"]
    artifacts = []
    with store.transaction() as conn:
        for name in names:
            relative = (target / name).relative_to(service.root).as_posix()
            artifacts.append(store.register_artifact(row["portfolio_id"], row["id"], relative, connection=conn))
        result = {"report_id": row["id"], "artifact_ids": artifacts,
                  "valuation_as_of": saved["valuation_as_of"], "snapshot_id": manifest["snapshot_id"]}
        conn.execute("UPDATE jobs SET status='published',error_code=NULL,result_json=?,updated_at=? WHERE id=?",
                     (json.dumps(result), store.clock(), row["id"]))


def reconcile_one(store, jobs, row):
    """Called only with the job guard; a running child cannot be reconciled."""
    _, project = store.portfolio(row["portfolio_id"])
    if row["kind"] in {"preview", "record_preview", "source_plan"}:
        jobs.state(row["id"], "interrupted", error="preview_interrupted")
        return
    try:
        with project_lock(project):
            service = ApplicationService(resolve_workspace(explicit=project))
            saved = next((op for op in service.operations() if op["operation_id"] == row["core_operation_id"]), None)
            if row["kind"] == "record" and saved and saved["status"] == "data_only_complete":
                from .financial import safe_record
                jobs.state(row["id"], "recorded", result={"operation_id":row["core_operation_id"],
                    "report_published":False, "result":safe_record(saved["result"])})
            elif saved and saved["status"] == "published":
                publish_registry(store, jobs, row, service, saved)
            elif saved and saved["status"] in {"data_committed", "report_failed"}:
                # The financial transaction contains this commit marker. Requeue
                # only the same operation; execute_job selects report-only resume.
                jobs.state(row["id"], "queued", error="report_recovery_queued")
            elif saved and saved["status"] == "data_failed":
                jobs.state(row["id"], "failed", error="input_rejected")
            else:
                jobs.state(row["id"], "needs_review", error="commit_state_requires_review")
    except LockBusy:
        return
    except Exception:
        jobs.state(row["id"], "needs_review", error="recovery_requires_review")


def reconcile(store):
    jobs = Jobs(store)
    with closing(store.connect()) as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM jobs WHERE status IN ('running','data_committed')")]
    for row in rows:
        try:
            with job_guard(store, row["id"]):
                reconcile_one(store, jobs, row)
        except LockBusy:
            pass


def execute_job(settings, job_id):
    store = Store(settings); jobs = Jobs(store)
    row = jobs.internal(job_id)
    from .maintenance import instance_activity
    with instance_activity(store.root), job_guard(store, job_id):
        if not jobs.claim(job_id):
            return
        row = jobs.internal(job_id)
        _, project = store.portfolio(row["portfolio_id"])
        service = ApplicationService(resolve_workspace(explicit=project))
        try:
            if row["kind"] == "source_plan":
                from .source_plans import execute_plan
                execute_plan(store, jobs, row)
                return
            if row["kind"] == "record_preview":
                from .financial import declaration_upload, preview_declaration
                before = input_fingerprint(project)
                upload = declaration_upload(store,row)
                request = json.loads(row["request_json"])["declaration"]
                preview = preview_declaration(project,request,upload_path=upload,now=row["execution_at"])
                if input_fingerprint(project) != before:
                    jobs.state(job_id,"blocked",error="stale_preview");return
                jobs.state(job_id,"ready",result=safe_preview(preview,project,store.root/"uploads"),fingerprint=before)
                return
            if row["kind"] == "record":
                execute_record(store,jobs,row,service)
                return
            if row["kind"] == "preview":
                core = jobs.core_request(row)
                before = input_fingerprint(project)
                from ..i18n import presentation_context
                from ..settings import report_locale
                with presentation_context(report_locale(project)):
                    preview = service.preview(core, now=datetime.fromisoformat(row["execution_at"]))
                if input_fingerprint(project) != before:
                    jobs.state(job_id, "blocked", error="stale_preview")
                    return
                preview = safe_preview(preview, project, store.root / "uploads")
                jobs.state(job_id, "blocked" if preview["status"] == "blocked" else "ready",
                           result=preview, fingerprint=before)
                return
            saved = next((op for op in service.operations() if op["operation_id"] == row["core_operation_id"]), None)
            if saved and saved["status"] == "published":
                with project_lock(project):
                    publish_registry(store, jobs, row, service, saved)
                return
            if saved and saved["status"] not in {"data_committed", "report_failed"}:
                jobs.state(job_id, "needs_review", error="commit_state_requires_review")
                return
            core = {} if saved else jobs.core_request(row)
            service.update(core, resume=row["core_operation_id"] if saved else None,
                operation_id=None if saved else row["core_operation_id"],
                expected_fingerprint=None if saved else row["input_fingerprint"],
                on_data_committed=lambda operation: jobs.state(job_id, "data_committed"))
            saved = service.operation(row["core_operation_id"])
            with project_lock(project):
                publish_registry(store, jobs, row, service, saved)
        except LockBusy:
            jobs.state(job_id, "queued", error="portfolio_busy")
        except Exception as exc:
            if row["kind"] in {"preview", "record_preview", "source_plan"}:
                jobs.state(job_id, "blocked", error=exc.code if isinstance(exc, WebError) else "preview_failed")
                return
            saved = next((op for op in service.operations() if op["operation_id"] == row["core_operation_id"]), None)
            if row["kind"] == "record" and saved and saved["status"] == "data_only_complete":
                from .financial import safe_record
                jobs.state(job_id,"recorded",result={"operation_id":row["core_operation_id"],
                    "report_published":False,"result":safe_record(saved["result"])})
            elif saved and saved["status"] in {"data_committed", "report_failed"}:
                jobs.state(job_id, "report_failed", error="report_failed")
            elif saved and saved["status"] == "data_failed":
                jobs.state(job_id, "failed", error="input_rejected")
            elif not saved:
                code = exc.code if isinstance(exc, WebError) else ("stale_preview" if input_fingerprint(project) != row["input_fingerprint"] else "request_rejected")
                jobs.state(job_id, "blocked", error=code)
            else:
                jobs.state(job_id, "needs_review", error="execution_requires_review")


def execute_record(store, jobs, row, service):
    from .financial import apply_declaration, declaration_upload, safe_record
    saved = next((op for op in service.operations() if op["operation_id"] == row["core_operation_id"]), None)
    if saved:
        if saved["status"] == "data_only_complete":
            jobs.state(row["id"],"recorded",result={"operation_id":row["core_operation_id"],
                "report_published":False,"result":safe_record(saved["result"])})
        else:
            jobs.state(row["id"],"needs_review",error="commit_state_requires_review")
        return
    upload = declaration_upload(store,row)
    request = json.loads(row["request_json"])["declaration"]
    result = service.record(request,lambda stage:apply_declaration(stage,request,upload_path=upload,now=row["execution_at"]),
        label="before-web-declaration",operation_id=row["core_operation_id"],expected_fingerprint=row["input_fingerprint"])
    jobs.state(row["id"],"recorded",result={"operation_id":row["core_operation_id"],
        "report_published":False,"result":safe_record(result)})


def execute_isolated(settings, job_id):
    # Fixed module/arguments; no user-supplied program, task name, shell or pickle.
    env = {**os.environ, "WEALTH_LEDGER_DATA_ROOT": str(settings.data_root),
           "WEALTH_LEDGER_PUBLIC_ORIGIN": settings.public_origin, "PYTHONPATH": str(PACKAGE_ROOT.parent),
           "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-m", "wealth_ledger.web.worker", job_id], env=env,
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def run_worker(settings, *, once=False):
    from .queue import make_queue, notify_pending
    store = Store(settings)
    if not store.owner():
        raise ValueError("Initialize the owner before starting a worker")
    with file_lock(contained(store.root, "admin/worker.guard")):
        from .maintenance import instance_activity
        with instance_activity(store.root):
            reconcile(store)
            queue, dispatch = make_queue(store)
            notify_pending(store, dispatch, force=True)
        if once:
            while (task := queue.dequeue()) is not None:
                queue.execute(task)
            return
        stopped = threading.Event()
        def pulse():
            while not stopped.wait(5):
                try:
                    with instance_activity(store.root):
                        reconcile(store)
                        notify_pending(store, dispatch)
                except Exception:
                    # Persisted jobs remain authoritative; retry the notification
                    # scan, never dump financial request/exception values to logs.
                    pass
        monitor = threading.Thread(target=pulse, daemon=True)
        monitor.start()
        try:
            queue.create_consumer(workers=1, worker_type="thread", periodic=False,
                                  initial_delay=0.2, max_delay=2).run()
        finally:
            stopped.set(); monitor.join(timeout=6)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("An internal job ID is required")
    execute_job(WebSettings.from_environment(), sys.argv[1])
