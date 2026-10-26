"""Initial isolated candidate/transaction/job foundation, never a legacy migration."""
import uuid
from alembic import op
from sqlalchemy import text
from wealth_ledger.persistence.schema import ddl
revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    script, _, _ = ddl()
    op.get_bind().exec_driver_sql(script)
    op.get_bind().execute(text("INSERT INTO wl_pg.instance_state VALUES(1,:incarnation,0,true)"),
                          {"incarnation":uuid.uuid4()})

def downgrade():
    raise RuntimeError("Destructive downgrade is not supported")
