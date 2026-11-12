"""Durable Excel lead imports.

Revision ID: 0012_excel_leads
Revises: 0011_trainee_training_variables
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_excel_leads"
down_revision = "0011_trainee_training_variables"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "imported_leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("upload_id", sa.String(36), nullable=False),
        sa.Column("sheet_row", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("upload_id", "sheet_row", name="uq_imported_leads_upload_row"),
    )
    op.create_index("ix_imported_leads_upload_id", "imported_leads", ["upload_id"])


def downgrade():
    op.drop_table("imported_leads")
