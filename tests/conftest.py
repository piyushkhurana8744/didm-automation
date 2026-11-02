import os

# Tests construct isolated Settings/database instances. Never allow repository credentials to enter a
# test process merely because the developer has a local .env file.
os.environ["DIDM_LOAD_DOTENV"] = "false"

import pytest

from app.saas import passwords


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch):
    """Real scrypt, but with small parameters so the suite stays fast. Production uses N=2^15, p=3."""
    monkeypatch.setattr(passwords, "SCRYPT_N", 2 ** 10)
    monkeypatch.setattr(passwords, "SCRYPT_P", 1)


def fresh_db_url(tmp_path) -> str:
    """A new empty database for one test. SQLite by default; set TEST_POSTGRES_URL (a server URL whose user
    may create databases, e.g. postgresql://postgres@localhost:5432/postgres) to run the suite on PostgreSQL."""
    import os
    import uuid
    base = os.getenv("TEST_POSTGRES_URL")
    if not base:
        return f"sqlite:///{tmp_path}/t.db"
    import sqlalchemy as sa
    from app.db import make_engine
    name = "didm_test_" + uuid.uuid4().hex[:12]
    eng = make_engine(base)
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(sa.text(f'CREATE DATABASE "{name}"'))
    eng.dispose()
    return sa.engine.make_url(base).set(database=name).render_as_string(hide_password=False)
