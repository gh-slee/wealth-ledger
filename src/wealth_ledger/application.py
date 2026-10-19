"""Workspace-scoped application services shared by CLI and future job workers."""
from __future__ import annotations

from functools import partial
from contextlib import closing
import sqlite3

from . import operations
from .publishing import database_backup, publish
from .workspace import Workspace, resolve_workspace


class ApplicationService:
    """No shell commands, HTTP context or mutable project-path globals."""

    def __init__(self, workspace: Workspace):
        # Revalidate when a service is constructed; never silently use the checkout.
        self.workspace = resolve_workspace(explicit=workspace.workspace_root)
        self.root = self.workspace.workspace_root

    def accounts(self):
        """Stable flow-import identities, without creating or modifying a ledger."""
        if not self.workspace.database.exists():
            return []
        with closing(sqlite3.connect(self.workspace.database.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(
                "SELECT account_id,label,masked_number FROM accounts ORDER BY account_id")]

    def preview(self, request, **kwargs):
        from .preflight import preview_update
        return preview_update(self.root, request, **kwargs)

    def operations(self):
        return operations.list_operations(self.root)

    def operation(self, operation_id):
        return operations.get(self.root, operation_id)

    def update(self, request, *, resume=None, operation_id=None, expected_fingerprint=None, on_data_committed=None):
        from .workflow import identify_inputs, validate_update_request
        if not resume:
            from .source_ingestion import require_report_projection
            require_report_projection(self.root)
            # Core services also validate requests; callers need not be CLI parsers.
            validate_update_request(request)
            identified = identify_inputs(request.get("paths", []))
            if request.get("wealthsimple_only") and "bullbitcoin" in identified:
                raise ValueError("Brokerage-only mode cannot include a Bull CSV")
        with operations.project_lock(self.root):
            if expected_fingerprint is not None and operations.input_fingerprint(self.root) != expected_fingerprint:
                raise ValueError("Preview is stale; financial or configuration inputs changed")
            database_backup(self.root, "before-auto-update")
            result = operations.execute_update(self.root, request, partial(publish, self.root),
                                               resume=resume, operation_id=operation_id, on_data_committed=on_data_committed)
        pending = [r["operation_id"] for r in self.operations()
                   if r["status"] in ("data_committed", "report_failed")]
        if pending:
            result["pending_report_operations"] = pending
        return result

    def record(self, request, action, *, label, operation_id=None, expected_fingerprint=None, require_clear_operations=False):
        """Shared lock, backup, staged commit and recovery record for data-only edits."""
        with operations.project_lock(self.root):
            saved = next((row for row in self.operations() if row["operation_id"] == operation_id), None) if operation_id else None
            if not saved and require_clear_operations and any(row["status"] in {"started","data_started","data_committed","report_failed"}
                    for row in self.operations()):
                raise ValueError("Unfinished financial operation requires review")
            if not saved and expected_fingerprint is not None and operations.input_fingerprint(self.root) != expected_fingerprint:
                raise ValueError("Preview is stale; financial or configuration inputs changed")
            database_backup(self.root, label)
            return operations.record_data_operation(self.root, request, action, operation_id=operation_id)

    def source_payload(self, **inputs):
        """Read source-neutral report inputs; never publish or change a ledger."""
        from .source_report import make_source_payload
        return make_source_payload(self.root, **inputs)

    def source_valuation(self, inputs, *, operation_id=None, expected_fingerprint=None):
        """Freeze an explicit source valuation, with atomic receipt-only recovery."""
        from copy import deepcopy
        from .source_valuation import freeze_valuation
        from .source_projection import _serialize
        values = deepcopy(_serialize(inputs))
        return self.record({"type": "source_report_valuation", "inputs": values},
            lambda stage: freeze_valuation(stage, **values), label="before-source-valuation",
            operation_id=operation_id, expected_fingerprint=expected_fingerprint, require_clear_operations=True)

    def source_report_preview(self, paths=(), **options):
        """Prepare a frozen source/report approval, without live financial writes."""
        from .source_publication import prepare_source_report
        return prepare_source_report(self.root, paths, **options)

    def source_report_confirm(self, directory, approval_sha256, **options):
        from .source_publication import confirm_source_report
        return confirm_source_report(self.root, directory, approval_sha256, **options)

    def source_report_resume(self, operation_id, **options):
        from .source_publication import resume_source_report
        return resume_source_report(self.root, operation_id, **options)
