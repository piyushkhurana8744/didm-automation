"""Retain Sarvam outbound history and resumable sync cursors."""
from alembic import op
import sqlalchemy as sa

revision = "0015_outbound_history"
down_revision = "0014_campaign_mode"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "outbound_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("attempt_id", sa.String(200), nullable=False),
        sa.Column("interaction_id", sa.String(200), nullable=True),
        sa.Column("phone", sa.String(200), nullable=False),
        sa.Column("status", sa.String(80), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("campaign_id", sa.String(200), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("variables", sa.JSON(), nullable=False),
        sa.Column("transcript", sa.JSON(), nullable=False),
        sa.Column("transcript_retry_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("agent_id", "attempt_id", name="uq_outbound_agent_attempt"),
    )
    for column in ("organization_id", "agent_id", "started_at"):
        op.create_index(f"ix_outbound_calls_{column}", "outbound_calls", [column])
    op.create_table(
        "outbound_sync_states",
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), primary_key=True),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("window_end", sa.DateTime(), nullable=False),
        sa.Column("offset", sa.Integer(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("retry_at", sa.DateTime(), nullable=False),
        sa.Column("error", sa.String(200), nullable=True),
    )


def downgrade():
    op.drop_table("outbound_sync_states")
    op.drop_table("outbound_calls")
