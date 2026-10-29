"""Explicit source metadata only; no financial acceptance or legacy data migration."""
from alembic import context, op
from wealth_ledger.persistence import source_schema as source

revision = "0003_source_lifecycle"
down_revision = "0002_identity"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    fault = context.config.attributes.get("source_fault")
    def emit(sql):
        bind.exec_driver_sql(sql, execution_options={"no_parameters": True})
    header, tables = source.TABLE_DDL.split("CREATE TABLE", 1)
    emit(header)
    if fault: fault("after_new_schema")
    emit("CREATE TABLE" + tables)
    if fault: fault("after_tables")
    emit(source.table_ddl()[len(source.TABLE_DDL):] + source.identity_replacements())
    if fault: fault("after_replacement_guards")
    emit(source.gateway_ddl())
    if fault: fault("after_source_functions")


def downgrade():
    raise RuntimeError("Destructive sources downgrade is not supported")
