"""Database: every call, WhatsApp message, batch and alert is recorded here."""
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, Column, DateTime, Integer, String, Text,
                        UniqueConstraint, create_engine, event)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CallAttempt(Base):
    __tablename__ = "call_attempts"
    id = Column(Integer, primary_key=True)
    attempt_id = Column(String(64), unique=True, index=True, nullable=True)
    sheet_row = Column(Integer, index=True)
    phone = Column(String(20), index=True)
    name = Column(String(200))
    batch_id = Column(Integer, nullable=True)
    state = Column(String(20), default="calling")  # calling | done | start_failed | stuck
    status = Column(String(30), nullable=True)  # connected | no_answer | busy | failed
    outcome = Column(String(60), nullable=True)
    duration = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    raw_result = Column(JSON, nullable=True)
    started_at = Column(DateTime, default=utcnow)
    finished_at = Column(DateTime, nullable=True)
    dry_run = Column(Boolean, default=False)


class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"
    id = Column(Integer, primary_key=True)
    sheet_row = Column(Integer, index=True)
    phone = Column(String(20), index=True)
    template = Column(String(100))
    http_status = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=utcnow)
    dry_run = Column(Boolean, default=False)


class Batch(Base):
    __tablename__ = "batches"
    id = Column(Integer, primary_key=True)
    requested = Column(Integer)
    dialled = Column(Integer, default=0)
    min_row = Column(Integer, nullable=True)
    max_row = Column(Integer, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    finished_at = Column(DateTime, nullable=True)
    note = Column(String(200), nullable=True)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    level = Column(String(10))  # info | warn | error
    message = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    emailed = Column(Boolean, default=False)


class WebhookEvent(Base):
    """Every webhook delivery is stored here before it is processed, so none is lost if processing fails."""
    __tablename__ = "webhook_events"
    id = Column(String(36), primary_key=True)  # also the correlation id in logs
    source = Column(String(30), index=True)  # sarvam_result | event_call
    payload = Column(JSON)
    payload_hash = Column(String(64), index=True)
    attempt_id = Column(String(64), index=True, nullable=True)
    status = Column(String(12), default="pending", index=True)  # pending | processing | done | failed | dead
    attempts = Column(Integer, default=0)
    next_attempt_at = Column(DateTime, default=utcnow, index=True)
    locked_at = Column(DateTime, nullable=True)
    redacted_at = Column(DateTime, nullable=True)  # training bodies: replaced by a summary under retention
    last_error = Column(Text, nullable=True)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class WhatsAppClaim(Base):
    """One row per number and message kind. The unique key stops two workers sending the same message."""
    __tablename__ = "whatsapp_claims"
    __table_args__ = (UniqueConstraint("phone", "kind", name="uq_whatsapp_claims_phone_kind"),)
    id = Column(Integer, primary_key=True)
    phone = Column(String(20))
    kind = Column(String(100))  # "followup" or the event template name
    state = Column(String(10))  # sending | sent | failed
    updated_at = Column(DateTime, default=utcnow)


class Setting(Base):
    """Runtime switches that survive restarts, such as the stop switch."""
    __tablename__ = "settings"
    key = Column(String(50), primary_key=True)
    value = Column(String(200))


_engine = None
SessionLocal = sessionmaker(expire_on_commit=False)


def normalize_url(url: str) -> str:
    # Hosts often give postgres:// URLs; SQLAlchemy needs the driver named
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(url: str):
    url = normalize_url(url)
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
    else:
        # One web process with worker threads and the scheduler: keep well inside the database's
        # connection limit (DB_POOL_SIZE + DB_MAX_OVERFLOW per process)
        import os
        kwargs = {"pool_pre_ping": True, "pool_size": int(os.getenv("DB_POOL_SIZE") or 5),
                  "max_overflow": int(os.getenv("DB_MAX_OVERFLOW") or 5), "pool_recycle": 1800}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        # SQLite otherwise accepts rows that PostgreSQL correctly rejects, masking tenant/FK bugs in CI.
        @event.listens_for(engine, "connect")
        def _sqlite_foreign_keys(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def init_db(url: str, migrate: bool = True):
    """Connects and brings the schema up to date with the Alembic migrations in migrations/.

    The first migration only creates the original tables if they are missing, so a database
    that was set up by the old create_all keeps all its rows.
    """
    global _engine
    _engine = make_engine(url)
    if migrate:
        from .migrate import upgrade_head
        upgrade_head(_engine)
    SessionLocal.configure(bind=_engine)
    return _engine


def get_flag(session, key: str, default: str = "") -> str:
    row = session.get(Setting, key)
    return row.value if row else default


def set_flag(session, key: str, value: str):
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))
    session.commit()
