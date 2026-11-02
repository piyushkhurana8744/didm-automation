"""Trainee-owned training overlays for assigned agents.

Revision ID: 0010_trainee_agent_training
Revises: 0009_knowledge_domain
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_trainee_agent_training"
down_revision = "0009_knowledge_domain"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trainee_agent_training_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("variable_values", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("sources", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", "agent_id", name="uq_trainee_agent_training_owner"),
    )
    op.create_index("ix_trainee_agent_training_lookup", "trainee_agent_training_profiles",
                    ["organization_id", "user_id", "agent_id"])


def downgrade():
    op.drop_table("trainee_agent_training_profiles")
