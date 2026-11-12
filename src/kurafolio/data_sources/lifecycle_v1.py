"""Pure lifecycle availability and public error contracts; no financial writes."""
from .contract_v1 import MAX_COUNTER

STATUS = {
    "source_catalog_unavailable": 503, "source_unavailable": 409,
    "source_capability_unavailable": 409, "source_context_incompatible": 409,
    "source_connection_conflict": 409, "source_revision_conflict": 409,
    "source_idempotency_conflict": 409, "source_repreview_required": 409,
    "source_capacity_reached": 409, "source_counter_exhausted": 409,
    "source_commit_uncertain": 503,
}


class SourceError(Exception):
    def __init__(self, code="source_catalog_unavailable"):
        self.code = code if code in STATUS else "source_catalog_unavailable"
        self.status = STATUS[self.code]
        super().__init__(self.code)


def effective_status(*, capability, enabled, parent_enabled=True, generation="0",
                     root_revision="0", parent_generation="0", installation_id=None,
                     parent_installation_id=None, active_installation_id=None,
                     availability_generation="1", connection=False,
                     availability_status="ACTIVE", selected_availability_generation=None):
    if capability == "PULL_API":
        return "UNAVAILABLE", "source_capability_unavailable"
    if not enabled:
        return "DISABLED", None
    if connection and not parent_enabled:
        return "SOURCE_DISABLED", None
    counters=(generation,root_revision,parent_generation,availability_generation)
    if selected_availability_generation is not None:counters+= (selected_availability_generation,)
    if any(int(x) == MAX_COUNTER for x in counters):
        return "UNAVAILABLE", "source_counter_exhausted"
    if active_installation_id is None or availability_status=="REVOKED":
        return "UNAVAILABLE", "source_unavailable"
    if installation_id != active_installation_id or (connection and parent_installation_id != installation_id):
        return "CONFIRMATION_REQUIRED", None
    return "ENABLED", None
