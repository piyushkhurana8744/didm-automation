"""Provider-agnostic recording metadata and organization provider selection.

Revision ID: 0008_recording_providers
Revises: 0007_production
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_recording_providers"
down_revision = "0007_production"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("training_org_settings") as b:
        b.add_column(sa.Column("storage_provider", sa.String(20), nullable=True))
    with op.batch_alter_table("training_recordings") as b:
        b.add_column(sa.Column("storage_provider", sa.String(20), nullable=True))
        b.add_column(sa.Column("storage_asset_id", sa.String(300), nullable=True))
        b.add_column(sa.Column("storage_resource_type", sa.String(20), nullable=True))
        b.add_column(sa.Column("storage_delivery_type", sa.String(20), nullable=True))
        b.add_column(sa.Column("storage_version", sa.String(40), nullable=True))
        b.add_column(sa.Column("storage_status", sa.String(30), nullable=True))
        b.add_column(sa.Column("uploaded_at", sa.DateTime(), nullable=True))
        b.create_index("ix_training_recordings_provider_asset", ["storage_provider", "storage_asset_id"])


def downgrade():
    with op.batch_alter_table("training_recordings") as b:
        b.drop_index("ix_training_recordings_provider_asset")
        for name in ("uploaded_at", "storage_status", "storage_version", "storage_delivery_type",
                     "storage_resource_type", "storage_asset_id", "storage_provider"):
            b.drop_column(name)
    with op.batch_alter_table("training_org_settings") as b:
        b.drop_column("storage_provider")
