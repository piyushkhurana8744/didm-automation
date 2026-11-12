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
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("batches")}
    with op.batch_alter_table("batches") as batch:
        for name, kind in (("agent_id", sa.String(36)), ("agent_name", sa.String(200)),
                           ("provider_app_id", sa.String(200)), ("provider_app_version", sa.Integer()),
                           ("connection_id", sa.String(200)), ("agent_phone", sa.String(30))):
            if name not in existing:
                batch.add_column(sa.Column(name, kind))

def downgrade():
    with op.batch_alter_table("batches") as batch:
        for name in ("agent_phone", "connection_id", "provider_app_version", "provider_app_id", "agent_name", "agent_id"):
            batch.drop_column(name)
