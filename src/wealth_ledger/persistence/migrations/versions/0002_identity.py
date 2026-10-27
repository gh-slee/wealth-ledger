"""Opt-in identity only; old finance DDL/migration remains unchanged."""
from alembic import context, op
from sqlalchemy import text
from wealth_ledger.persistence.identity_schema import ddl

revision = "0002_identity"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade():
    import re
    digest = context.config.attributes.get("identity_key_digest")
    if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError("Explicit identity key digest required")
    bind = op.get_bind()
    bind.exec_driver_sql(ddl(), execution_options={"no_parameters": True})
    bind.execute(text("INSERT INTO wl_identity.instance_auth_state(id,key_digest,last_observed_at) VALUES(1,:digest,clock_timestamp())"), {"digest": digest})


def downgrade():
    raise RuntimeError("Destructive identity downgrade is not supported")
