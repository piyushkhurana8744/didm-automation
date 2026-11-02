"""Baseline: the five tables the automation app already had (created by create_all before Alembic).

On a database that already has them this revision changes nothing, so existing rows are kept.
On a new database it creates them.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _missing(name: str) -> bool:
    return not sa.inspect(op.get_bind()).has_table(name)


def upgrade():
    if _missing("call_attempts"):
        op.create_table(
            "call_attempts",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("attempt_id", sa.String(64), nullable=True),
            sa.Column("sheet_row", sa.Integer),
            sa.Column("phone", sa.String(20)),
            sa.Column("name", sa.String(200)),
            sa.Column("batch_id", sa.Integer, nullable=True),
            sa.Column("state", sa.String(20)),
            sa.Column("status", sa.String(30), nullable=True),
            sa.Column("outcome", sa.String(60), nullable=True),
            sa.Column("duration", sa.Integer, nullable=True),
            sa.Column("summary", sa.Text, nullable=True),
            sa.Column("error", sa.Text, nullable=True),
            sa.Column("raw_result", sa.JSON, nullable=True),
            sa.Column("started_at", sa.DateTime),
            sa.Column("finished_at", sa.DateTime, nullable=True),
            sa.Column("dry_run", sa.Boolean),
        )
        op.create_index("ix_call_attempts_attempt_id", "call_attempts", ["attempt_id"], unique=True)
        op.create_index("ix_call_attempts_sheet_row", "call_attempts", ["sheet_row"])
        op.create_index("ix_call_attempts_phone", "call_attempts", ["phone"])
    if _missing("whatsapp_messages"):
        op.create_table(
            "whatsapp_messages",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("sheet_row", sa.Integer),
            sa.Column("phone", sa.String(20)),
            sa.Column("template", sa.String(100)),
            sa.Column("http_status", sa.Integer, nullable=True),
            sa.Column("error", sa.Text, nullable=True),
            sa.Column("sent_at", sa.DateTime),
            sa.Column("dry_run", sa.Boolean),
        )
        op.create_index("ix_whatsapp_messages_sheet_row", "whatsapp_messages", ["sheet_row"])
        op.create_index("ix_whatsapp_messages_phone", "whatsapp_messages", ["phone"])
    if _missing("batches"):
        op.create_table(
            "batches",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("requested", sa.Integer),
            sa.Column("dialled", sa.Integer),
            sa.Column("min_row", sa.Integer, nullable=True),
            sa.Column("max_row", sa.Integer, nullable=True),
            sa.Column("active", sa.Boolean),
            sa.Column("created_at", sa.DateTime),
            sa.Column("finished_at", sa.DateTime, nullable=True),
            sa.Column("note", sa.String(200), nullable=True),
        )
    if _missing("alerts"):
        op.create_table(
            "alerts",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("level", sa.String(10)),
            sa.Column("message", sa.Text),
            sa.Column("created_at", sa.DateTime),
            sa.Column("emailed", sa.Boolean),
        )
    if _missing("settings"):
        op.create_table(
            "settings",
            sa.Column("key", sa.String(50), primary_key=True),
            sa.Column("value", sa.String(200)),
        )


def downgrade():
    # Never drop the original tables: they hold the live call history.
    pass
