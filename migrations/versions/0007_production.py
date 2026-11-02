"""Production readiness: evaluator usage metering and budgets, retention runs, legal holds, the practice-call
notice, recording deletion retries, transcript purge markers and webhook body redaction markers.

Only adds tables and nullable (or defaulted) columns; nothing existing is changed or removed.

Revision ID: 0007_production
Revises: 0006_intelligence
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_production"
down_revision = "0006_intelligence"
branch_labels = None
depends_on = None


def _fk(name, table, nullable=True, **kw):
    return sa.Column(name, sa.String(36), sa.ForeignKey(f"{table}.id"), nullable=nullable, **kw)


def upgrade():
    op.create_table(
        "evaluation_usage",
        sa.Column("id", sa.String(36), primary_key=True),
        _fk("organization_id", "organizations", nullable=False),
        _fk("session_id", "training_sessions", nullable=False),
        _fk("rubric_version_id", "evaluation_rubric_versions"),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("prompt_tokens", sa.Integer, nullable=True),
        sa.Column("completion_tokens", sa.Integer, nullable=True),
        sa.Column("total_tokens", sa.Integer, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_evaluation_usage_org_created", "evaluation_usage", ["organization_id", "created_at"])
    op.create_index("ix_evaluation_usage_created", "evaluation_usage", ["created_at"])
    op.create_index("ix_evaluation_usage_session_id", "evaluation_usage", ["session_id"])

    op.create_table(
        "retention_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        _fk("organization_id", "organizations"),
        sa.Column("enforced", sa.Boolean, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("counts", sa.JSON, nullable=False),
        sa.Column("error", sa.String(300), nullable=True),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_retention_runs_org_started", "retention_runs", ["organization_id", "started_at"])

    with op.batch_alter_table("training_org_limits") as b:
        b.add_column(sa.Column("evaluation_monthly_calls", sa.Integer, nullable=True))
        b.add_column(sa.Column("evaluation_monthly_tokens", sa.Integer, nullable=True))
    with op.batch_alter_table("training_org_settings") as b:
        b.add_column(sa.Column("practice_notice_text", sa.Text, nullable=True))
        b.add_column(sa.Column("practice_notice_version", sa.String(64), nullable=True))
        b.add_column(sa.Column("transcript_retention_days", sa.Integer, nullable=True))
        b.add_column(sa.Column("legal_hold", sa.Boolean, nullable=False, server_default=sa.text("false")))
        b.add_column(sa.Column("legal_hold_reason", sa.String(500), nullable=True))
        b.add_column(sa.Column("legal_hold_set_by", sa.String(36),
                               sa.ForeignKey("users.id", name="fk_training_org_settings_legal_hold_set_by_users"),
                               nullable=True))
        b.add_column(sa.Column("legal_hold_set_at", sa.DateTime, nullable=True))
    with op.batch_alter_table("training_sessions") as b:
        b.add_column(sa.Column("practice_notice_reference", sa.String(64), nullable=True))
    with op.batch_alter_table("training_transcripts") as b:
        b.add_column(sa.Column("purged_at", sa.DateTime, nullable=True))
    with op.batch_alter_table("training_recordings") as b:
        b.add_column(sa.Column("delete_attempts", sa.Integer, nullable=False, server_default=sa.text("0")))
        b.add_column(sa.Column("last_error", sa.String(120), nullable=True))
        b.add_column(sa.Column("verified_at", sa.DateTime, nullable=True))
    with op.batch_alter_table("training_evaluations") as b:
        b.add_column(sa.Column("total_tokens", sa.Integer, nullable=True))
        b.add_column(sa.Column("evidence_redacted_at", sa.DateTime, nullable=True))
    with op.batch_alter_table("webhook_events") as b:
        b.add_column(sa.Column("redacted_at", sa.DateTime, nullable=True))


def downgrade():
    """Drops what upgrade added. This deletes evaluator usage and retention history, so take a backup
    first; a code rollback does not need it, because every addition is optional for older code."""
    with op.batch_alter_table("webhook_events") as b:
        b.drop_column("redacted_at")
    with op.batch_alter_table("training_evaluations") as b:
        b.drop_column("evidence_redacted_at")
        b.drop_column("total_tokens")
    with op.batch_alter_table("training_recordings") as b:
        b.drop_column("verified_at")
        b.drop_column("last_error")
        b.drop_column("delete_attempts")
    with op.batch_alter_table("training_transcripts") as b:
        b.drop_column("purged_at")
    with op.batch_alter_table("training_sessions") as b:
        b.drop_column("practice_notice_reference")
    with op.batch_alter_table("training_org_settings") as b:
        b.drop_constraint("fk_training_org_settings_legal_hold_set_by_users", type_="foreignkey")
        for c in ("legal_hold_set_at", "legal_hold_set_by", "legal_hold_reason", "legal_hold",
                  "transcript_retention_days", "practice_notice_version", "practice_notice_text"):
            b.drop_column(c)
    with op.batch_alter_table("training_org_limits") as b:
        b.drop_column("evaluation_monthly_tokens")
        b.drop_column("evaluation_monthly_calls")
    op.drop_table("retention_runs")
    op.drop_table("evaluation_usage")
