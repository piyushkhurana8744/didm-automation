"""Voice agent registry: teams, agents, immutable agent versions, training scenarios and assignments.

Only adds tables; nothing existing is changed.

Revision ID: 0004_agents
Revises: 0003_identity
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_agents"
down_revision = "0003_identity"
branch_labels = None
depends_on = None


def _partial(where: str) -> dict:
    return {"postgresql_where": sa.text(where), "sqlite_where": sa.text(where)}


def _org():
    return sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False)


def _user_fk(name, nullable=True):
    return sa.Column(name, sa.String(36), sa.ForeignKey("users.id"), nullable=nullable)


def upgrade():
    op.create_table(
        "teams",
        sa.Column("id", sa.String(36), primary_key=True),
        _org(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        _user_fk("created_by"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("archived_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("organization_id", "name", name="uq_teams_org_name"),
    )
    op.create_index("ix_teams_organization_id", "teams", ["organization_id"])

    op.create_table(
        "team_members",
        sa.Column("id", sa.String(36), primary_key=True),
        _org(),
        sa.Column("team_id", sa.String(36), sa.ForeignKey("teams.id"), nullable=False),
        _user_fk("user_id", nullable=False),
        _user_fk("added_by"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("removed_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_team_members_organization_id", "team_members", ["organization_id"])
    op.create_index("ix_team_members_team_id", "team_members", ["team_id"])
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"])
    op.create_index("uq_team_members_active", "team_members", ["team_id", "user_id"], unique=True,
                    **_partial("removed_at IS NULL"))

    op.create_table(
        "agents",
        sa.Column("id", sa.String(36), primary_key=True),
        _org(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("provider_app_id", sa.String(200), nullable=False),
        sa.Column("channels", sa.JSON, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("published_version_id", sa.String(36), nullable=True),
        _user_fk("created_by"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("archived_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("provider", "provider_app_id", name="uq_agents_provider_app"),
    )
    op.create_index("ix_agents_organization_id", "agents", ["organization_id"])
    op.create_index("ix_agents_org_status", "agents", ["organization_id", "status"])

    op.create_table(
        "agent_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        _org(),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("internal_version", sa.Integer, nullable=False),
        sa.Column("provider_app_version", sa.Integer, nullable=True),
        sa.Column("configuration_snapshot", sa.JSON, nullable=False),
        sa.Column("variable_schema", sa.JSON, nullable=False),
        sa.Column("knowledge_base_reference", sa.String(500), nullable=False),
        sa.Column("rubric_reference", sa.String(500), nullable=False),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("based_on_version_id", sa.String(36), sa.ForeignKey("agent_versions.id"), nullable=True),
        _user_fk("created_by"),
        sa.Column("published_at", sa.DateTime, nullable=True),
        _user_fk("published_by"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("agent_id", "internal_version", name="uq_agent_versions_number"),
        sa.CheckConstraint("status IN ('draft', 'published')", name="ck_agent_versions_status"),
        sa.CheckConstraint("status = 'draft' OR (provider_app_version IS NOT NULL AND published_at IS NOT NULL)",
                           name="ck_agent_versions_published_complete"),
    )
    op.create_index("ix_agent_versions_organization_id", "agent_versions", ["organization_id"])
    op.create_index("ix_agent_versions_agent_id", "agent_versions", ["agent_id"])
    op.create_index("uq_agent_versions_one_draft", "agent_versions", ["agent_id"], unique=True,
                    **_partial("status = 'draft'"))

    op.create_table(
        "training_scenarios",
        sa.Column("id", sa.String(36), primary_key=True),
        _org(),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("difficulty", sa.String(20), nullable=False),
        sa.Column("persona", sa.Text, nullable=False),
        sa.Column("objective", sa.Text, nullable=False),
        sa.Column("opening_context", sa.Text, nullable=False),
        sa.Column("expected_behavior", sa.Text, nullable=False),
        sa.Column("evaluation_criteria_reference", sa.String(500), nullable=False),
        sa.Column("agent_variables", sa.JSON, nullable=False),
        sa.Column("validated_version_id", sa.String(36), sa.ForeignKey("agent_versions.id"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        _user_fk("created_by"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("archived_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_training_scenarios_organization_id", "training_scenarios", ["organization_id"])
    op.create_index("ix_training_scenarios_agent_status", "training_scenarios", ["agent_id", "status"])

    op.create_table(
        "agent_assignments",
        sa.Column("id", sa.String(36), primary_key=True),
        _org(),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        _user_fk("user_id"),
        sa.Column("team_id", sa.String(36), sa.ForeignKey("teams.id"), nullable=True),
        _user_fk("assigned_by"),
        sa.Column("starts_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        _user_fk("revoked_by"),
        sa.Column("revoke_reason", sa.String(40), nullable=True),
        sa.Column("settings", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("(user_id IS NULL) != (team_id IS NULL)", name="ck_agent_assignments_one_target"),
    )
    op.create_index("ix_agent_assignments_organization_id", "agent_assignments", ["organization_id"])
    op.create_index("ix_agent_assignments_agent_id", "agent_assignments", ["agent_id"])
    op.create_index("ix_agent_assignments_org_user", "agent_assignments", ["organization_id", "user_id"])
    op.create_index("ix_agent_assignments_org_team", "agent_assignments", ["organization_id", "team_id"])
    op.create_index("uq_agent_assignments_user_open", "agent_assignments", ["agent_id", "user_id"], unique=True,
                    **_partial("revoked_at IS NULL AND user_id IS NOT NULL"))
    op.create_index("uq_agent_assignments_team_open", "agent_assignments", ["agent_id", "team_id"], unique=True,
                    **_partial("revoked_at IS NULL AND team_id IS NOT NULL"))


def downgrade():
    for t in ("agent_assignments", "training_scenarios", "agent_versions", "agents", "team_members", "teams"):
        op.drop_table(t)
