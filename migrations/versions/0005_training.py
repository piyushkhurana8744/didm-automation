"""Training sessions: sessions, provider events, usage, capacity reservations, browser tokens, org limits,
and the trainee phone number columns.

Only adds tables and nullable columns; nothing existing is changed or removed.

Revision ID: 0005_training
Revises: 0004_agents
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_training"
down_revision = "0004_agents"
branch_labels = None
depends_on = None


def _partial(where: str) -> dict:
    return {"postgresql_where": sa.text(where), "sqlite_where": sa.text(where)}


def _fk(name, table, nullable=True, **kw):
    return sa.Column(name, sa.String(36), sa.ForeignKey(f"{table}.id"), nullable=nullable, **kw)


def upgrade():
    op.add_column("users", sa.Column("phone_e164", sa.String(20), nullable=True))
    with op.batch_alter_table("memberships") as b:
        b.add_column(sa.Column("verified_phone_e164", sa.String(20), nullable=True))
        b.add_column(sa.Column("phone_verified_at", sa.DateTime, nullable=True))
        b.add_column(sa.Column("phone_verified_by", sa.String(36), nullable=True))
        b.create_foreign_key("fk_memberships_phone_verified_by_users", "users", ["phone_verified_by"], ["id"])

    op.create_table(
        "training_org_limits",
        _fk("organization_id", "organizations", nullable=False, primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("phone_enabled", sa.Boolean, nullable=False),
        sa.Column("browser_enabled", sa.Boolean, nullable=False),
        sa.Column("max_concurrent_sessions", sa.Integer, nullable=True),
        sa.Column("max_concurrent_per_user", sa.Integer, nullable=True),
        sa.Column("max_sessions_per_user_per_day", sa.Integer, nullable=True),
        sa.Column("max_session_minutes", sa.Integer, nullable=True),
        sa.Column("monthly_minutes", sa.Integer, nullable=True),
        _fk("updated_by", "users"),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "training_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        _fk("organization_id", "organizations", nullable=False),
        _fk("user_id", "users", nullable=False),
        sa.Column("client_request_id", sa.String(64), nullable=True),
        sa.Column("assignment_ids", sa.JSON, nullable=False),
        sa.Column("access_snapshot", sa.JSON, nullable=False),
        _fk("agent_id", "agents", nullable=False),
        _fk("agent_version_id", "agent_versions", nullable=False),
        _fk("scenario_id", "training_scenarios"),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("provider_app_id", sa.String(200), nullable=False),
        sa.Column("provider_app_version", sa.Integer, nullable=False),
        sa.Column("resolved_variables", sa.JSON, nullable=False),
        sa.Column("resolved_configuration", sa.JSON, nullable=False),
        sa.Column("phone_last4", sa.String(4), nullable=True),
        sa.Column("provider_session_id", sa.String(200), nullable=True),
        sa.Column("provider_attempt_id", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("failure_code", sa.String(60), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column("max_duration_seconds", sa.Integer, nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("connected_at", sa.DateTime, nullable=True),
        sa.Column("ended_at", sa.DateTime, nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column("billable_seconds", sa.Integer, nullable=True),
        sa.Column("usage_finalized_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("channel IN ('phone', 'browser')", name="ck_training_sessions_channel"),
        sa.CheckConstraint("status IN ('requested', 'preparing', 'connecting', 'active', 'completed', 'failed', "
                           "'cancelled', 'timed_out')", name="ck_training_sessions_status"),
    )
    op.create_index("uq_training_sessions_request", "training_sessions",
                    ["organization_id", "user_id", "client_request_id"], unique=True,
                    **_partial("client_request_id IS NOT NULL"))
    op.create_index("uq_training_sessions_attempt", "training_sessions", ["provider", "provider_attempt_id"],
                    unique=True, **_partial("provider_attempt_id IS NOT NULL"))
    op.create_index("ix_training_sessions_org_status", "training_sessions", ["organization_id", "status"])
    op.create_index("ix_training_sessions_org_user_created", "training_sessions",
                    ["organization_id", "user_id", "created_at"])
    op.create_index("ix_training_sessions_org_created", "training_sessions", ["organization_id", "created_at"])
    op.create_index("ix_training_sessions_status_updated", "training_sessions", ["status", "updated_at"])

    op.create_table(
        "training_session_events",
        sa.Column("id", sa.String(36), primary_key=True),
        _fk("organization_id", "organizations", nullable=False),
        _fk("session_id", "training_sessions", nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("provider_event_id", sa.String(128), nullable=True),
        sa.Column("event_payload", sa.JSON, nullable=False),
        sa.Column("occurred_at", sa.DateTime, nullable=False),
        sa.Column("received_at", sa.DateTime, nullable=False),
        sa.Column("processed_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_training_session_events_organization_id", "training_session_events", ["organization_id"])
    op.create_index("ix_training_session_events_session_id", "training_session_events", ["session_id"])
    op.create_index("uq_training_session_events_provider", "training_session_events",
                    ["session_id", "provider_event_id"], unique=True, **_partial("provider_event_id IS NOT NULL"))

    op.create_table(
        "training_usage_events",
        sa.Column("id", sa.String(36), primary_key=True),
        _fk("organization_id", "organizations", nullable=False),
        _fk("user_id", "users", nullable=False),
        _fk("session_id", "training_sessions", nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("metric", sa.String(40), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("session_id", "metric", name="uq_training_usage_session_metric"),
    )
    op.create_index("ix_training_usage_org_created", "training_usage_events", ["organization_id", "created_at"])

    op.create_table(
        "training_usage_reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        _fk("organization_id", "organizations", nullable=False),
        _fk("user_id", "users", nullable=False),
        _fk("session_id", "training_sessions", nullable=False, unique=True),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("reserved_seconds", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("status IN ('reserved', 'confirmed', 'settled', 'released', 'expired')",
                           name="ck_training_reservations_status"),
    )
    op.create_index("ix_training_reservations_org_status", "training_usage_reservations", ["organization_id", "status"])

    op.create_table(
        "browser_session_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        _fk("organization_id", "organizations", nullable=False),
        _fk("session_id", "training_sessions", nullable=False, unique=True),
        _fk("user_id", "users", nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("provider_reference_id", sa.String(200), nullable=True),
        sa.Column("issued_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("used_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_browser_session_tokens_organization_id", "browser_session_tokens", ["organization_id"])


def downgrade():
    for t in ("browser_session_tokens", "training_usage_reservations", "training_usage_events",
              "training_session_events", "training_sessions", "training_org_limits"):
        op.drop_table(t)
    with op.batch_alter_table("memberships") as b:
        b.drop_constraint("fk_memberships_phone_verified_by_users", type_="foreignkey")
        b.drop_column("phone_verified_by")
        b.drop_column("phone_verified_at")
        b.drop_column("verified_phone_e164")
    op.drop_column("users", "phone_e164")
