"""Install the ingestion schema only inside the explicit operator transaction."""
from alembic import context, op
from kurafolio.persistence import ingestion_migration, ingestion_schema

revision = "0004_ingestion"
down_revision = "0003_source_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    attributes = context.config.attributes
    roles = attributes.get("ingestion_operator_roles")
    if roles is None:
        raise RuntimeError("Explicit ingestion operator transaction required")

    bind = op.get_bind()
    runtime_role, owner_role = roles
    fault = attributes.get("ingestion_fault")
    for phase, ddl in (
        ("after_tables", ingestion_schema.tables_ddl),
        ("after_replacement_guards", ingestion_migration.inherited_guard_replacements),
        ("after_functions", ingestion_migration.function_ddl),
        ("after_policies", lambda: ingestion_schema.policies_ddl(runtime_role, owner_role)),
        ("after_triggers", ingestion_schema.triggers_ddl),
    ):
        bind.exec_driver_sql(ddl(), execution_options={"no_parameters": True})
        if fault is not None:
            fault(phase)


def downgrade():
    raise RuntimeError("Destructive ingestion downgrade is not supported")
