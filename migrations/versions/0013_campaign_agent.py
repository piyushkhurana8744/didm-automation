"""Pin every calling batch to a published voice agent.

Revision ID: 0013_campaign_agent
Revises: 0012_excel_leads
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_campaign_agent"
down_revision = "0012_excel_leads"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("batches") as batch:
        batch.add_column(sa.Column("agent_id", sa.String(36)))
        batch.add_column(sa.Column("agent_name", sa.String(200)))
        batch.add_column(sa.Column("provider_app_id", sa.String(200)))
        batch.add_column(sa.Column("provider_app_version", sa.Integer()))
        batch.add_column(sa.Column("connection_id", sa.String(200)))
        batch.add_column(sa.Column("agent_phone", sa.String(30)))

def downgrade():
    with op.batch_alter_table("batches") as batch:
        for name in ("agent_phone", "connection_id", "provider_app_version", "provider_app_id", "agent_name", "agent_id"):
            batch.drop_column(name)
