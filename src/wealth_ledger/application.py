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

    def record(self, request, action, *, label):
        """Shared lock, backup, staged commit and recovery record for data-only edits."""
        with operations.project_lock(self.root):
            database_backup(self.root, label)
            return operations.record_data_operation(self.root, request, action)
