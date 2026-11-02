"""Training intelligence: transcripts, recordings metadata, rubrics, evaluations, post-call jobs, usage
adjustments, phone verification codes, and a few nullable columns on existing tables.

Only adds tables and columns; nothing existing is changed or removed. No audio is stored in the database.

Revision ID: 0006_intelligence
Revises: 0005_training
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_intelligence"
down_revision = "0005_training"
branch_labels = None
depends_on = None


def _partial(where: str) -> dict:
    return {"postgresql_where": sa.text(where), "sqlite_where": sa.text(where)}


def _fk(name, table, nullable=True, **kw):
    return sa.Column(name, sa.String(36), sa.ForeignKey(f"{table}.id"), nullable=nullable, **kw)


def _id():
    return sa.Column("id", sa.String(36), primary_key=True)


def upgrade():
    op.create_table(
        "evaluation_rubrics", _id(),
        _fk("organization_id", "organizations", nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        _fk("created_by", "users"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("organization_id", "name", name="uq_evaluation_rubrics_org_name"),
    )
    op.create_index("ix_evaluation_rubrics_organization_id", "evaluation_rubrics", ["organization_id"])

    op.create_table(
        "evaluation_rubric_versions", _id(),
        _fk("organization_id", "organizations", nullable=False),
        _fk("rubric_id", "evaluation_rubrics", nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("criteria", sa.JSON, nullable=False),
        sa.Column("weights", sa.JSON, nullable=False),
        sa.Column("scale_max", sa.Integer, nullable=False),
        sa.Column("scoring_instructions", sa.Text, nullable=False),
        sa.Column("min_trainee_turns", sa.Integer, nullable=False),
        _fk("created_by", "users"),
        sa.Column("published_at", sa.DateTime, nullable=True),
        _fk("published_by", "users"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("rubric_id", "version", name="uq_rubric_versions_number"),
        sa.CheckConstraint("status IN ('draft', 'published')", name="ck_rubric_versions_status"),
        sa.CheckConstraint("status = 'draft' OR published_at IS NOT NULL", name="ck_rubric_versions_published_complete"),
    )
    op.create_index("ix_evaluation_rubric_versions_organization_id", "evaluation_rubric_versions", ["organization_id"])
    op.create_index("ix_evaluation_rubric_versions_rubric_id", "evaluation_rubric_versions", ["rubric_id"])
    op.create_index("uq_rubric_versions_one_draft", "evaluation_rubric_versions", ["rubric_id"], unique=True,
                    **_partial("status = 'draft'"))

    op.create_table(
        "training_org_settings",
        _fk("organization_id", "organizations", nullable=False, primary_key=True),
        sa.Column("recording_enabled", sa.Boolean, nullable=False),
        sa.Column("recording_retention_days", sa.Integer, nullable=False),
        sa.Column("consent_version", sa.String(64), nullable=True),
        sa.Column("consent_text", sa.Text, nullable=False),
        _fk("default_rubric_id", "evaluation_rubrics"),
        _fk("updated_by", "users"),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    with op.batch_alter_table("training_org_limits") as b:
        b.add_column(sa.Column("evaluation_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")))
        b.add_column(sa.Column("recording_allowed", sa.Boolean, nullable=False, server_default=sa.text("false")))
    with op.batch_alter_table("training_sessions") as b:
        b.add_column(sa.Column("provider_status", sa.String(60), nullable=True))
        b.add_column(sa.Column("provider_duration_seconds", sa.Integer, nullable=True))
        b.add_column(sa.Column("reconciliation_status", sa.String(20), nullable=True))
        b.add_column(sa.Column("reconciled_at", sa.DateTime, nullable=True))
        b.add_column(sa.Column("recording_consent_reference", sa.String(64), nullable=True))
    with op.batch_alter_table("training_scenarios") as b:
        b.add_column(sa.Column("rubric_id", sa.String(36), nullable=True))
        b.create_foreign_key("fk_training_scenarios_rubric_id_evaluation_rubrics", "evaluation_rubrics",
                             ["rubric_id"], ["id"])
    with op.batch_alter_table("memberships") as b:
        b.add_column(sa.Column("phone_verification_method", sa.String(20), nullable=True))

    op.create_table(
        "training_transcripts", _id(),
        _fk("organization_id", "organizations", nullable=False),
        _fk("session_id", "training_sessions", nullable=False, unique=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("language", sa.String(20), nullable=True),
        sa.Column("text_variant", sa.String(30), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("status_reason", sa.String(300), nullable=True),
        sa.Column("provider_reference", sa.String(200), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("turn_count", sa.Integer, nullable=False),
        sa.Column("trainee_turn_count", sa.Integer, nullable=False),
        sa.Column("fetched_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("status IN ('complete', 'partial', 'missing', 'failed')", name="ck_training_transcripts_status"),
    )
    op.create_index("ix_training_transcripts_org_created", "training_transcripts", ["organization_id", "created_at"])

    op.create_table(
        "training_transcript_turns", _id(),
        _fk("organization_id", "organizations", nullable=False),
        _fk("transcript_id", "training_transcripts", nullable=False),
        sa.Column("sequence_number", sa.Integer, nullable=False),
        sa.Column("speaker", sa.String(10), nullable=False),
        sa.Column("provider_role", sa.String(30), nullable=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("start_ms", sa.Integer, nullable=True),
        sa.Column("end_ms", sa.Integer, nullable=True),
        sa.UniqueConstraint("transcript_id", "sequence_number", name="uq_transcript_turns_sequence"),
        sa.CheckConstraint("speaker IN ('agent', 'trainee', 'unknown')", name="ck_transcript_turns_speaker"),
    )
    op.create_index("ix_training_transcript_turns_organization_id", "training_transcript_turns", ["organization_id"])

    op.create_table(
        "training_recordings", _id(),
        _fk("organization_id", "organizations", nullable=False),
        _fk("session_id", "training_sessions", nullable=False, unique=True),
        sa.Column("storage_key", sa.String(300), nullable=True, unique=True),
        sa.Column("provider_reference", sa.String(200), nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column("content_type", sa.String(60), nullable=True),
        sa.Column("size_bytes", sa.Integer, nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("status_reason", sa.String(300), nullable=True),
        sa.Column("retention_until", sa.DateTime, nullable=True),
        sa.Column("consent_reference", sa.String(64), nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("status IN ('pending', 'stored', 'unavailable', 'failed', 'deleted')",
                           name="ck_training_recordings_status"),
    )
    op.create_index("ix_training_recordings_organization_id", "training_recordings", ["organization_id"])
    op.create_index("ix_training_recordings_status_retention", "training_recordings", ["status", "retention_until"])

    op.create_table(
        "training_evaluations", _id(),
        _fk("organization_id", "organizations", nullable=False),
        _fk("session_id", "training_sessions", nullable=False),
        _fk("rubric_version_id", "evaluation_rubric_versions", nullable=False),
        sa.Column("evaluator_provider", sa.String(40), nullable=False),
        sa.Column("evaluator_model", sa.String(100), nullable=False),
        sa.Column("evaluator_version", sa.String(40), nullable=False),
        sa.Column("scoring_config", sa.JSON, nullable=False),
        sa.Column("transcript_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("overall_score", sa.Integer, nullable=True),
        sa.Column("confidence", sa.Integer, nullable=True),
        sa.Column("criterion_results", sa.JSON, nullable=False),
        sa.Column("feedback", sa.JSON, nullable=False),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("evaluated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("session_id", "rubric_version_id", name="uq_training_evaluations_session_rubric"),
        sa.CheckConstraint("status IN ('completed', 'insufficient_evidence', 'failed')",
                           name="ck_training_evaluations_status"),
        sa.CheckConstraint("status = 'completed' OR overall_score IS NULL",
                           name="ck_training_evaluations_score_only_completed"),
    )
    op.create_index("ix_training_evaluations_session_id", "training_evaluations", ["session_id"])
    op.create_index("ix_training_evaluations_org_evaluated", "training_evaluations", ["organization_id", "evaluated_at"])

    op.create_table(
        "evaluation_jobs", _id(),
        _fk("organization_id", "organizations", nullable=False),
        _fk("session_id", "training_sessions", nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("max_attempts", sa.Integer, nullable=False),
        sa.Column("next_attempt_at", sa.DateTime, nullable=False),
        sa.Column("locked_until", sa.DateTime, nullable=True),
        sa.Column("job_input", sa.JSON, nullable=False),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("last_error", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("session_id", "kind", name="uq_evaluation_jobs_session_kind"),
        sa.CheckConstraint("kind IN ('transcript', 'evaluation', 'recording', 'reconcile')", name="ck_evaluation_jobs_kind"),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'skipped', 'dead')",
                           name="ck_evaluation_jobs_status"),
    )
    op.create_index("ix_evaluation_jobs_organization_id", "evaluation_jobs", ["organization_id"])
    op.create_index("ix_evaluation_jobs_status_next", "evaluation_jobs", ["status", "next_attempt_at"])

    op.create_table(
        "training_usage_adjustments", _id(),
        _fk("organization_id", "organizations", nullable=False),
        _fk("user_id", "users", nullable=False),
        _fk("session_id", "training_sessions", nullable=False),
        sa.Column("metric", sa.String(40), nullable=False),
        sa.Column("delta", sa.Integer, nullable=False),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("session_id", "metric", "reason", name="uq_training_usage_adjustments_once"),
    )
    op.create_index("ix_training_usage_adjustments_org_created", "training_usage_adjustments",
                    ["organization_id", "created_at"])

    op.create_table(
        "phone_verification_challenges", _id(),
        _fk("organization_id", "organizations", nullable=False),
        _fk("membership_id", "memberships", nullable=False),
        _fk("user_id", "users", nullable=False),
        sa.Column("phone_e164", sa.String(20), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("max_attempts", sa.Integer, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("consumed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_phone_verification_challenges_organization_id", "phone_verification_challenges",
                    ["organization_id"])
    op.create_index("ix_phone_challenges_membership_created", "phone_verification_challenges",
                    ["membership_id", "created_at"])


def downgrade():
    for t in ("phone_verification_challenges", "training_usage_adjustments", "evaluation_jobs", "training_evaluations",
              "training_recordings", "training_transcript_turns", "training_transcripts"):
        op.drop_table(t)
    with op.batch_alter_table("memberships") as b:
        b.drop_column("phone_verification_method")
    with op.batch_alter_table("training_scenarios") as b:
        b.drop_constraint("fk_training_scenarios_rubric_id_evaluation_rubrics", type_="foreignkey")
        b.drop_column("rubric_id")
    with op.batch_alter_table("training_sessions") as b:
        for c in ("recording_consent_reference", "reconciled_at", "reconciliation_status", "provider_duration_seconds",
                  "provider_status"):
            b.drop_column(c)
    with op.batch_alter_table("training_org_limits") as b:
        b.drop_column("recording_allowed")
        b.drop_column("evaluation_enabled")
    op.drop_table("training_org_settings")
    op.drop_table("evaluation_rubric_versions")
    op.drop_table("evaluation_rubrics")
