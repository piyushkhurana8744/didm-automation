"""Persist the selected live/test mode for each batch, including across restarts."""
from alembic import op
import sqlalchemy as sa

revision = "0014_campaign_mode"
down_revision = "0013_campaign_agent"
branch_labels = None
depends_on = None


def upgrade():
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("batches")}
    if "dry_run" not in existing:
        with op.batch_alter_table("batches") as batch:
            batch.add_column(sa.Column("dry_run", sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table("batches") as batch:
        batch.drop_column("dry_run")
