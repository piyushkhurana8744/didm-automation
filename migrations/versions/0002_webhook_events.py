"""Durable webhook events and WhatsApp send claims.

Revision ID: 0002_webhook_events
Revises: 0001_baseline
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_webhook_events"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(30)),
        sa.Column("payload", sa.JSON),
        sa.Column("payload_hash", sa.String(64)),
        sa.Column("attempt_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(12)),
        sa.Column("attempts", sa.Integer),
        sa.Column("next_attempt_at", sa.DateTime),
        sa.Column("locked_at", sa.DateTime, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("result", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )
    for col in ("source", "payload_hash", "attempt_id", "status", "next_attempt_at"):
        op.create_index(f"ix_webhook_events_{col}", "webhook_events", [col])
    op.create_table(
        "whatsapp_claims",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("phone", sa.String(20)),
        sa.Column("kind", sa.String(100)),
        sa.Column("state", sa.String(10)),
        sa.Column("updated_at", sa.DateTime),
        sa.UniqueConstraint("phone", "kind", name="uq_whatsapp_claims_phone_kind"),
    )


def downgrade():
    op.drop_table("whatsapp_claims")
    op.drop_table("webhook_events")
