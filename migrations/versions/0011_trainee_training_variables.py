"""Add personal variable values without rewriting applied migration 0010.

Revision ID: 0011_trainee_training_variables
Revises: 0010_trainee_agent_training
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_trainee_training_variables"
down_revision = "0010_trainee_agent_training"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("trainee_agent_training_profiles") as batch:
        batch.add_column(sa.Column("variable_values", sa.JSON(), nullable=False,
                                   server_default=sa.text("'{}'")))


def downgrade():
    with op.batch_alter_table("trainee_agent_training_profiles") as batch:
        batch.drop_column("variable_values")
