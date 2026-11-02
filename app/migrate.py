"""Runs the Alembic migrations from code, so the app, the tests and the command line all build the same schema."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
MIGRATION_LOCK = 7340212  # PostgreSQL advisory lock id: only one process migrates at a time


def alembic_config(url: str | None = None) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade_head(engine) -> None:
    cfg = alembic_config()
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            # Two instances starting together (or a pre-deploy step racing a start) wait for each other;
            # the second then finds nothing to do. Released when this transaction ends.
            conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": MIGRATION_LOCK})
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def schema_status(engine) -> dict:
    """The database's migration revision next to the code's, for the readiness check."""
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return {"current": current, "head": head, "up_to_date": current == head}


if __name__ == "__main__":  # python -m app.migrate: the controlled migration step for deployments
    import os

    from .db import make_engine

    eng = make_engine(os.environ["DATABASE_URL"])
    upgrade_head(eng)
    print(schema_status(eng))
