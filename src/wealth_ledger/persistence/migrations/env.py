"""Alembic uses only the explicit operator transaction supplied by the caller."""
from alembic import context
connection = context.config.attributes.get("connection")
if connection is None or context.is_offline_mode():
    raise RuntimeError("Explicit online operator transaction required")
context.configure(connection=connection,version_table_schema="wl_pg",transaction_per_migration=False)
with context.begin_transaction():
    context.run_migrations()
