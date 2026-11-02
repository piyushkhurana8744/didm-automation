"""Alembic environment. Uses the app's models as the target schema and DATABASE_URL for the connection."""
import os

from alembic import context

from app.db import Base, make_engine
from app.saas import models  # noqa: F401  (registers the SaaS tables on Base.metadata)

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or os.getenv("DATABASE_URL", "sqlite:///./didm.db")


def run_offline():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online():
    conn = config.attributes.get("connection")
    if conn is not None:  # called from app.migrate with an open connection
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = make_engine(_url())
    with engine.begin() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
