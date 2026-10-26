"""Bounded persistence diagnostics without SQL, credentials or source values."""
CODES = frozenset("""invalid_config invalid_context invalid_candidate database_unavailable
schema_unsupported request_conflict stale_generation revision_conflict parent_missing
reference_conflict lease_lost job_state attempts_exhausted counter_exhausted
retry_exhausted migration_target_invalid migration_role_required restore_required
resource_limit""".split())

class PersistenceError(ValueError):
    def __init__(self, code):
        self.code = code if code in CODES else "invalid_candidate"
        super().__init__(self.code)
