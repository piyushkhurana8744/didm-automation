"""Tables for the training SaaS: organizations, users, memberships, invitations, login sessions and audit.

Every tenant-owned row carries organization_id. Ids are UUID strings so they work on Postgres and SQLite.
"""
import uuid

from sqlalchemy import (JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index,
                        Integer, String, Text, UniqueConstraint, event, inspect, text)

from ..db import Base, utcnow


def new_id() -> str:
    return str(uuid.uuid4())


class Organization(Base):
    __tablename__ = "organizations"
    id = Column(String(36), primary_key=True, default=new_id)
    name = Column(String(200), nullable=False)
    slug = Column(String(80), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="active")  # active | suspended
    settings = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class User(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True, default=new_id)
    email = Column(String(320), nullable=False, unique=True)  # stored lower-case
    name = Column(String(200), nullable=False, default="")
    password_hash = Column(String(300), nullable=True)
    status = Column(String(20), nullable=False, default="active")  # active | disabled
    is_platform_admin = Column(Boolean, nullable=False, default=False)
    phone_e164 = Column(String(20), nullable=True)  # set by the user; an org admin verifies it per organization
    email_verified_at = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_memberships_org_user"),)
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(30), nullable=False)  # organization_owner | organization_admin | trainer | trainee
    status = Column(String(20), nullable=False, default="active")  # active | revoked
    # The number an admin of this organization confirmed. Phone training needs it to equal users.phone_e164,
    # so changing the number makes it unverified again.
    verified_phone_e164 = Column(String(20), nullable=True)
    phone_verified_at = Column(DateTime, nullable=True)
    phone_verified_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    # How the number was verified: admin_confirmed (an admin typed the number they confirmed) or otp.
    # Empty on rows verified before Phase 4, which were all admin-confirmed.
    phone_verification_method = Column(String(20), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (Index("ix_invitations_org_email", "organization_id", "email"),)
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    email = Column(String(320), nullable=False)
    role = Column(String(30), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)  # only the SHA-256 of the secret is kept
    status = Column(String(20), nullable=False, default="pending")  # pending | accepted | revoked
    invited_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    accepted_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class AuthSession(Base):
    """A browser login. The cookie holds a random token; only its SHA-256 is stored."""
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_expires_at", "expires_at"),)
    id = Column(String(36), primary_key=True, default=new_id)
    token_hash = Column(String(64), nullable=False, unique=True)
    csrf_hash = Column(String(64), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    active_organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)
    ip = Column(String(64), nullable=True)
    user_agent = Column(String(300), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=True, index=True)
    actor_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(60), nullable=False)
    target_type = Column(String(40), nullable=True)
    target_id = Column(String(64), nullable=True)
    details = Column(JSON, nullable=True)
    ip = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)



def _partial(where: str) -> dict:
    """Index options for a partial (filtered) index on both Postgres and SQLite."""
    return {"postgresql_where": text(where), "sqlite_where": text(where)}


# ---------- teams ----------
class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_teams_org_name"),)
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String(20), nullable=False, default="active")  # active | archived
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    archived_at = Column(DateTime, nullable=True)


class TeamMember(Base):
    """A user in a team. Removing someone sets removed_at, so history is kept."""
    __tablename__ = "team_members"
    __table_args__ = (Index("uq_team_members_active", "team_id", "user_id", unique=True,
                            **_partial("removed_at IS NULL")),)
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    team_id = Column(String(36), ForeignKey("teams.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    added_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    removed_at = Column(DateTime, nullable=True)


# ---------- voice agents ----------
class Agent(Base):
    """An organization's link to a voice agent hosted at a provider (Sarvam).

    Creating this row does not create anything at Sarvam: the agent is built in Sarvam's dashboard and
    registered here by its app id. One provider app can belong to only one organization.
    """
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("provider", "provider_app_id", name="uq_agents_provider_app"),
                      Index("ix_agents_org_status", "organization_id", "status"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    category = Column(String(80), nullable=False, default="")
    provider = Column(String(30), nullable=False, default="sarvam")
    provider_app_id = Column(String(200), nullable=False)
    channels = Column(JSON, nullable=False, default=list)  # subset of ["phone", "browser"]
    status = Column(String(20), nullable=False, default="active")  # active | archived
    published_version_id = Column(String(36), nullable=True)  # newest published version, if any
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    archived_at = Column(DateTime, nullable=True)


class AgentVersion(Base):
    """One configuration of an agent. Drafts can be edited; a published version never changes, so a
    training session can point at it and always know which provider app version it used."""
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "internal_version", name="uq_agent_versions_number"),
                      Index("uq_agent_versions_one_draft", "agent_id", unique=True, **_partial("status = 'draft'")),
                      CheckConstraint("status IN ('draft', 'published')", name="ck_agent_versions_status"),
                      CheckConstraint("release_state IN ('legacy', 'draft', 'validating', 'validation_failed', "
                                      "'ready', 'provider_sync_pending', 'provider_sync_failed', "
                                      "'provider_synced', 'published')", name="ck_agent_versions_release_state"),
                      CheckConstraint("status = 'draft' OR (provider_app_version IS NOT NULL AND published_at IS NOT NULL)",
                                      name="ck_agent_versions_published_complete"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False, index=True)
    internal_version = Column(Integer, nullable=False)
    provider_app_version = Column(Integer, nullable=True)
    configuration_snapshot = Column(JSON, nullable=False, default=dict)
    variable_schema = Column(JSON, nullable=False, default=list)
    knowledge_base_reference = Column(String(500), nullable=False, default="")
    rubric_reference = Column(String(500), nullable=False, default="")
    notes = Column(Text, nullable=False, default="")
    # Phase 1 knowledge/release fields are nullable/defaulted so every historical version remains valid.
    behavior_snapshot = Column(JSON, nullable=False, default=dict)
    knowledge_snapshot_id = Column(String(36), nullable=True)
    provider_sync_id = Column(String(36), nullable=True)
    validation_report_id = Column(String(36), nullable=True)
    release_state = Column(String(30), nullable=False, default="draft")
    content_hash = Column(String(64), nullable=True)
    status = Column(String(20), nullable=False, default="draft")  # draft | published
    based_on_version_id = Column(String(36), ForeignKey("agent_versions.id"), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    published_at = Column(DateTime, nullable=True)
    published_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class TrainingScenario(Base):
    __tablename__ = "training_scenarios"
    __table_args__ = (Index("ix_training_scenarios_agent_status", "agent_id", "status"),)
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    difficulty = Column(String(20), nullable=False, default="beginner")  # beginner | intermediate | advanced
    persona = Column(Text, nullable=False, default="")
    objective = Column(Text, nullable=False, default="")
    opening_context = Column(Text, nullable=False, default="")
    expected_behavior = Column(Text, nullable=False, default="")
    evaluation_criteria_reference = Column(String(500), nullable=False, default="")
    rubric_id = Column(String(36), ForeignKey("evaluation_rubrics.id"), nullable=True)  # evaluates its sessions
    agent_variables = Column(JSON, nullable=False, default=dict)
    validated_version_id = Column(String(36), ForeignKey("agent_versions.id"), nullable=True)
    status = Column(String(20), nullable=False, default="draft")  # draft | active | archived
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    archived_at = Column(DateTime, nullable=True)


class AgentAssignment(Base):
    """Gives one user, or every member of one team, access to an agent for a period."""
    __tablename__ = "agent_assignments"
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) != (team_id IS NULL)", name="ck_agent_assignments_one_target"),
        Index("uq_agent_assignments_user_open", "agent_id", "user_id", unique=True,
              **_partial("revoked_at IS NULL AND user_id IS NOT NULL")),
        Index("uq_agent_assignments_team_open", "agent_id", "team_id", unique=True,
              **_partial("revoked_at IS NULL AND team_id IS NOT NULL")),
        Index("ix_agent_assignments_org_user", "organization_id", "user_id"),
        Index("ix_agent_assignments_org_team", "organization_id", "team_id"),
    )
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    team_id = Column(String(36), ForeignKey("teams.id"), nullable=True)
    assigned_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    starts_at = Column(DateTime, nullable=False, default=utcnow)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    revoke_reason = Column(String(40), nullable=True)  # revoked | replaced
    settings = Column(JSON, nullable=False, default=dict)  # allowed_scenario_ids, max_sessions, max_minutes_per_session
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


# ---------- training sessions (phase 3) ----------
OPEN_SESSION_STATUSES = ("requested", "preparing", "connecting", "active")


class TrainingOrgLimits(Base):
    """Training switches and caps for one organization. Only platform admins change these, because
    every minute costs DIDM money. A missing row or an empty field means the platform default."""
    __tablename__ = "training_org_limits"
    organization_id = Column(String(36), ForeignKey("organizations.id"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    phone_enabled = Column(Boolean, nullable=False, default=True)
    browser_enabled = Column(Boolean, nullable=False, default=False)
    max_concurrent_sessions = Column(Integer, nullable=True)
    max_concurrent_per_user = Column(Integer, nullable=True)
    max_sessions_per_user_per_day = Column(Integer, nullable=True)
    max_session_minutes = Column(Integer, nullable=True)
    monthly_minutes = Column(Integer, nullable=True)
    # Platform switches for the Phase 4 features that cost money or hold sensitive data
    evaluation_enabled = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    recording_allowed = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Evaluator budgets (phase 5). Empty means the platform default (EVALUATION_DEFAULT_MONTHLY_*)
    evaluation_monthly_calls = Column(Integer, nullable=True)
    evaluation_monthly_tokens = Column(Integer, nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class TrainingSession(Base):
    __tablename__ = "training_sessions"
    __table_args__ = (
        CheckConstraint("channel IN ('phone', 'browser')", name="ck_training_sessions_channel"),
        CheckConstraint("status IN ('requested', 'preparing', 'connecting', 'active', 'completed', 'failed', "
                        "'cancelled', 'timed_out')", name="ck_training_sessions_status"),
        Index("uq_training_sessions_request", "organization_id", "user_id", "client_request_id", unique=True,
              **_partial("client_request_id IS NOT NULL")),
        Index("uq_training_sessions_attempt", "provider", "provider_attempt_id", unique=True,
              **_partial("provider_attempt_id IS NOT NULL")),
        Index("ix_training_sessions_org_status", "organization_id", "status"),
        Index("ix_training_sessions_org_user_created", "organization_id", "user_id", "created_at"),
        Index("ix_training_sessions_org_created", "organization_id", "created_at"),
        Index("ix_training_sessions_status_updated", "status", "updated_at"),
    )
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    client_request_id = Column(String(64), nullable=True)  # makes a repeated start request return the same session
    assignment_ids = Column(JSON, nullable=False, default=list)  # the assignments that authorized it
    access_snapshot = Column(JSON, nullable=False, default=dict)  # source, limits and expiry at start
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False)
    agent_version_id = Column(String(36), ForeignKey("agent_versions.id"), nullable=False)
    scenario_id = Column(String(36), ForeignKey("training_scenarios.id"), nullable=True)
    channel = Column(String(10), nullable=False)
    provider = Column(String(30), nullable=False)
    provider_app_id = Column(String(200), nullable=False)
    provider_app_version = Column(Integer, nullable=False)
    resolved_variables = Column(JSON, nullable=False, default=dict)
    resolved_configuration = Column(JSON, nullable=False, default=dict)
    phone_last4 = Column(String(4), nullable=True)  # the full number is never kept on the session
    provider_session_id = Column(String(200), nullable=True)  # e.g. Sarvam interaction id
    provider_attempt_id = Column(String(200), nullable=True)  # Sarvam outbound attempt id
    status = Column(String(20), nullable=False, default="requested")
    failure_code = Column(String(60), nullable=True)
    failure_reason = Column(String(500), nullable=True)
    max_duration_seconds = Column(Integer, nullable=False)
    started_at = Column(DateTime, nullable=True)
    connected_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    billable_seconds = Column(Integer, nullable=True)
    usage_finalized_at = Column(DateTime, nullable=True)
    # What the provider reported, kept apart from our own state: a result can arrive after the session
    # already ended here (timed out, or failed because the start request timed out)
    provider_status = Column(String(60), nullable=True)
    provider_duration_seconds = Column(Integer, nullable=True)
    reconciliation_status = Column(String(20), nullable=True)  # pending | matched | corrected | unresolved
    reconciled_at = Column(DateTime, nullable=True)
    recording_consent_reference = Column(String(64), nullable=True)  # the consent notice the trainee accepted
    practice_notice_reference = Column(String(64), nullable=True)  # the practice-call notice the trainee accepted
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class TrainingSessionEvent(Base):
    __tablename__ = "training_session_events"
    __table_args__ = (Index("uq_training_session_events_provider", "session_id", "provider_event_id", unique=True,
                            **_partial("provider_event_id IS NOT NULL")),)
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("training_sessions.id"), nullable=False, index=True)
    event_type = Column(String(60), nullable=False)
    provider_event_id = Column(String(128), nullable=True)
    event_payload = Column(JSON, nullable=False, default=dict)  # redacted: no audio, keys or signed URLs
    occurred_at = Column(DateTime, nullable=False, default=utcnow)
    received_at = Column(DateTime, nullable=False, default=utcnow)
    processed_at = Column(DateTime, nullable=True)


class TrainingUsageEvent(Base):
    __tablename__ = "training_usage_events"
    __table_args__ = (UniqueConstraint("session_id", "metric", name="uq_training_usage_session_metric"),
                      Index("ix_training_usage_org_created", "organization_id", "created_at"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("training_sessions.id"), nullable=False)
    channel = Column(String(10), nullable=False)
    metric = Column(String(40), nullable=False)  # sessions | billable_seconds
    quantity = Column(Integer, nullable=False)
    source = Column(String(40), nullable=False)  # provider_result | browser_client | timeout | cancelled
    created_at = Column(DateTime, nullable=False, default=utcnow)


class TrainingUsageReservation(Base):
    """Capacity held for one session from the moment it is requested until it ends."""
    __tablename__ = "training_usage_reservations"
    __table_args__ = (
        CheckConstraint("status IN ('reserved', 'confirmed', 'settled', 'released', 'expired')",
                        name="ck_training_reservations_status"),
        Index("ix_training_reservations_org_status", "organization_id", "status"),
    )
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("training_sessions.id"), nullable=False, unique=True)
    channel = Column(String(10), nullable=False)
    reserved_seconds = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="reserved")
    expires_at = Column(DateTime, nullable=False)  # a reservation not confirmed by then is reclaimed
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class BrowserSessionToken(Base):
    """Metadata of a browser voice authorization. The signed provider URL itself is never stored, only
    its SHA-256, and one session can be authorized once (the provider URL is single-use)."""
    __tablename__ = "browser_session_tokens"
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("training_sessions.id"), nullable=False, unique=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    provider_reference_id = Column(String(200), nullable=True)
    issued_at = Column(DateTime, nullable=False, default=utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)


# ---------- training intelligence (phase 4) ----------
class TrainingOrgSettings(Base):
    """What an organization's admins choose for recordings and evaluation. The platform switches in
    TrainingOrgLimits must also allow a feature before these settings have any effect."""
    __tablename__ = "training_org_settings"
    organization_id = Column(String(36), ForeignKey("organizations.id"), primary_key=True)
    recording_enabled = Column(Boolean, nullable=False, default=False)
    recording_retention_days = Column(Integer, nullable=False, default=30)
    # Null means the platform default. Credentials are always platform-owned configuration.
    storage_provider = Column(String(20), nullable=True)
    consent_version = Column(String(64), nullable=True)  # trainees accept this exact notice per session
    consent_text = Column(Text, nullable=False, default="")
    default_rubric_id = Column(String(36), ForeignKey("evaluation_rubrics.id"), nullable=True)
    # Phase 5. A notice shown before every practice call (transcription, AI scoring); when set, a trainee
    # must accept this exact version to start a session
    practice_notice_text = Column(Text, nullable=True)
    practice_notice_version = Column(String(64), nullable=True)
    # Transcripts and the quotes in evaluations are removed this many days after the session. Empty keeps them
    transcript_retention_days = Column(Integer, nullable=True)
    # A legal hold stops every retention deletion for the organization, recordings included
    legal_hold = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    legal_hold_reason = Column(String(500), nullable=True)
    legal_hold_set_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    legal_hold_set_at = Column(DateTime, nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class TrainingTranscript(Base):
    """The provider's transcript of one session. Text is only ever what the provider sent: nothing is
    generated or filled in. Sarvam sends English (or English-translated) text, recorded in text_variant."""
    __tablename__ = "training_transcripts"
    __table_args__ = (
        CheckConstraint("status IN ('complete', 'partial', 'missing', 'failed')", name="ck_training_transcripts_status"),
        Index("ix_training_transcripts_org_created", "organization_id", "created_at"),
    )
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("training_sessions.id"), nullable=False, unique=True)
    source = Column(String(30), nullable=False)  # provider_webhook | provider_api
    language = Column(String(20), nullable=True)
    text_variant = Column(String(30), nullable=True)  # e.g. en_text: English or translated to English
    status = Column(String(20), nullable=False)
    status_reason = Column(String(300), nullable=True)
    provider_reference = Column(String(200), nullable=True)  # Sarvam interaction id
    content_hash = Column(String(64), nullable=True)
    turn_count = Column(Integer, nullable=False, default=0)
    trainee_turn_count = Column(Integer, nullable=False, default=0)
    fetched_at = Column(DateTime, nullable=True)
    purged_at = Column(DateTime, nullable=True)  # turns removed under the retention policy
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class TrainingTranscriptTurn(Base):
    __tablename__ = "training_transcript_turns"
    __table_args__ = (UniqueConstraint("transcript_id", "sequence_number", name="uq_transcript_turns_sequence"),
                      CheckConstraint("speaker IN ('agent', 'trainee', 'unknown')", name="ck_transcript_turns_speaker"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    transcript_id = Column(String(36), ForeignKey("training_transcripts.id"), nullable=False)
    sequence_number = Column(Integer, nullable=False)  # the provider's order, from 1
    speaker = Column(String(10), nullable=False)
    provider_role = Column(String(30), nullable=True)  # the role exactly as the provider sent it
    text = Column(Text, nullable=False)
    start_ms = Column(Integer, nullable=True)  # Sarvam sends no turn timings, so these stay empty for now
    end_ms = Column(Integer, nullable=True)


class TraineeAgentTrainingProfile(Base):
    """A trainee-owned training overlay for one currently assigned agent.

    It never mutates the shared agent/version. Sources contain extracted text only; uploaded binaries are
    not retained. Assignment checks are repeated on every API operation and when a call is created.
    """
    __tablename__ = "trainee_agent_training_profiles"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", "agent_id",
                                      name="uq_trainee_agent_training_owner"),
                      Index("ix_trainee_agent_training_lookup", "organization_id", "user_id", "agent_id"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False)
    instructions = Column(Text, nullable=False, default="")
    variable_values = Column(JSON, nullable=False, default=dict)
    sources = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class TrainingRecording(Base):
    """Where a session's audio is kept. The audio itself lives in private object storage, never here."""
    __tablename__ = "training_recordings"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'stored', 'unavailable', 'failed', 'deleted')",
                        name="ck_training_recordings_status"),
        Index("ix_training_recordings_status_retention", "status", "retention_until"),
        Index("ix_training_recordings_provider_asset", "storage_provider", "storage_asset_id"),
    )
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("training_sessions.id"), nullable=False, unique=True)
    storage_key = Column(String(300), nullable=True, unique=True)
    storage_provider = Column(String(20), nullable=True)
    storage_asset_id = Column(String(300), nullable=True)
    storage_resource_type = Column(String(20), nullable=True)
    storage_delivery_type = Column(String(20), nullable=True)
    storage_version = Column(String(40), nullable=True)
    storage_status = Column(String(30), nullable=True)
    uploaded_at = Column(DateTime, nullable=True)
    provider_reference = Column(String(200), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    content_type = Column(String(60), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    sha256 = Column(String(64), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    status_reason = Column(String(300), nullable=True)
    retention_until = Column(DateTime, nullable=True)
    consent_reference = Column(String(64), nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    # Phase 5: deletion that failed at the store is retried; verified_at is the last time the object was seen
    delete_attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    last_error = Column(String(120), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class EvaluationRubric(Base):
    __tablename__ = "evaluation_rubrics"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_evaluation_rubrics_org_name"),)
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String(20), nullable=False, default="active")  # active | archived
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class EvaluationRubricVersion(Base):
    """Criteria and weights for scoring. A published version never changes, so every evaluation can say
    exactly which rules produced its scores."""
    __tablename__ = "evaluation_rubric_versions"
    __table_args__ = (
        UniqueConstraint("rubric_id", "version", name="uq_rubric_versions_number"),
        Index("uq_rubric_versions_one_draft", "rubric_id", unique=True, **_partial("status = 'draft'")),
        CheckConstraint("status IN ('draft', 'published')", name="ck_rubric_versions_status"),
        CheckConstraint("status = 'draft' OR published_at IS NOT NULL", name="ck_rubric_versions_published_complete"),
    )
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    rubric_id = Column(String(36), ForeignKey("evaluation_rubrics.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="draft")
    criteria = Column(JSON, nullable=False, default=list)  # [{key, name, description, weight}]
    weights = Column(JSON, nullable=False, default=dict)  # {key: weight}, copied from criteria at publish
    scale_max = Column(Integer, nullable=False, default=5)  # criterion scores run from 0 to this
    scoring_instructions = Column(Text, nullable=False, default="")
    min_trainee_turns = Column(Integer, nullable=False, default=3)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    published_at = Column(DateTime, nullable=True)
    published_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class TrainingEvaluation(Base):
    """One scoring of one session against one published rubric version. A finished evaluation is never
    edited; re-evaluating with a new rubric version adds a new row."""
    __tablename__ = "training_evaluations"
    __table_args__ = (
        UniqueConstraint("session_id", "rubric_version_id", name="uq_training_evaluations_session_rubric"),
        CheckConstraint("status IN ('completed', 'insufficient_evidence', 'failed')",
                        name="ck_training_evaluations_status"),
        CheckConstraint("status = 'completed' OR overall_score IS NULL", name="ck_training_evaluations_score_only_completed"),
        Index("ix_training_evaluations_org_evaluated", "organization_id", "evaluated_at"),
    )
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("training_sessions.id"), nullable=False, index=True)
    rubric_version_id = Column(String(36), ForeignKey("evaluation_rubric_versions.id"), nullable=False)
    evaluator_provider = Column(String(40), nullable=False)
    evaluator_model = Column(String(100), nullable=False, default="")
    evaluator_version = Column(String(40), nullable=False)  # our prompt and output-schema version
    scoring_config = Column(JSON, nullable=False, default=dict)
    transcript_hash = Column(String(64), nullable=True)
    status = Column(String(30), nullable=False)
    overall_score = Column(Integer, nullable=True)  # 0-100, only when status is completed
    confidence = Column(Integer, nullable=True)  # 0-100
    criterion_results = Column(JSON, nullable=False, default=list)
    feedback = Column(JSON, nullable=False, default=dict)  # summary, strengths, improvements, practice topics
    evidence = Column(JSON, nullable=False, default=list)  # quotes, each checked against the transcript
    error_code = Column(String(60), nullable=True)
    evaluated_at = Column(DateTime, nullable=False, default=utcnow)
    # Phase 5: the evaluator's token count for the call that produced this result (all calls are in
    # evaluation_usage). Quotes are removed with the transcript under retention; scores stay.
    total_tokens = Column(Integer, nullable=True)
    evidence_redacted_at = Column(DateTime, nullable=True)


class EvaluationJob(Base):
    """Durable post-call work for one session: importing the transcript, evaluating it, copying the
    recording and reconciling the provider's outcome. One row per session and kind; claimed with a
    conditional update so only one worker runs it, and retried with exponential backoff."""
    __tablename__ = "evaluation_jobs"
    __table_args__ = (
        UniqueConstraint("session_id", "kind", name="uq_evaluation_jobs_session_kind"),
        CheckConstraint("kind IN ('transcript', 'evaluation', 'recording', 'reconcile')", name="ck_evaluation_jobs_kind"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'skipped', 'dead')", name="ck_evaluation_jobs_status"),
        Index("ix_evaluation_jobs_status_next", "status", "next_attempt_at"),
    )
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("training_sessions.id"), nullable=False)
    kind = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=6)
    next_attempt_at = Column(DateTime, nullable=False, default=utcnow)
    locked_until = Column(DateTime, nullable=True)
    job_input = Column(JSON, nullable=False, default=dict)  # provider data waiting to be imported; cleared after
    error_code = Column(String(60), nullable=True)
    last_error = Column(String(300), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)
    finished_at = Column(DateTime, nullable=True)


class TrainingUsageAdjustment(Base):
    """A correction to a session's usage after the fact, for example when the provider's result arrives
    after we billed the session's maximum. Usage events are never edited: corrections add here."""
    __tablename__ = "training_usage_adjustments"
    __table_args__ = (UniqueConstraint("session_id", "metric", "reason", name="uq_training_usage_adjustments_once"),
                      Index("ix_training_usage_adjustments_org_created", "organization_id", "created_at"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("training_sessions.id"), nullable=False)
    metric = Column(String(40), nullable=False)  # billable_seconds
    delta = Column(Integer, nullable=False)
    reason = Column(String(40), nullable=False)  # provider_reconciliation
    source = Column(String(40), nullable=False)  # late_webhook | provider_api
    evidence = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class PhoneVerificationChallenge(Base):
    """One code sent to a trainee's phone. Only the code's hash is kept. Used only when an OTP sender
    is configured; otherwise numbers are admin-confirmed and labelled so."""
    __tablename__ = "phone_verification_challenges"
    __table_args__ = (Index("ix_phone_challenges_membership_created", "membership_id", "created_at"),)
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    membership_id = Column(String(36), ForeignKey("memberships.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    phone_e164 = Column(String(20), nullable=False)
    code_hash = Column(String(64), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


# ---------- production readiness (phase 5) ----------
class EvaluationUsage(Base):
    """One evaluator call, successful or not, with the tokens the provider reported. Budgets are checked
    against these rows before every call, so a retry loop can never run up an unbounded bill."""
    __tablename__ = "evaluation_usage"
    __table_args__ = (Index("ix_evaluation_usage_org_created", "organization_id", "created_at"),
                      Index("ix_evaluation_usage_created", "created_at"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("training_sessions.id"), nullable=False, index=True)
    rubric_version_id = Column(String(36), ForeignKey("evaluation_rubric_versions.id"), nullable=True)
    provider = Column(String(40), nullable=False)
    model = Column(String(100), nullable=False, default="")
    outcome = Column(String(30), nullable=False)  # ok | invalid_output | error code
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class RetentionRun(Base):
    """One run of the retention job for one organization (or the platform, organization_id empty). With
    enforcement off it only counts what it would remove, so the owner can review before switching it on."""
    __tablename__ = "retention_runs"
    __table_args__ = (Index("ix_retention_runs_org_started", "organization_id", "started_at"),)
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)
    enforced = Column(Boolean, nullable=False)
    status = Column(String(20), nullable=False)  # completed | partial | held | failed
    counts = Column(JSON, nullable=False, default=dict)  # {category: {"due": n, "removed": n, "failed": n}}
    error = Column(String(300), nullable=True)
    started_at = Column(DateTime, nullable=False, default=utcnow)
    finished_at = Column(DateTime, nullable=True)


# ---------- agent knowledge and immutable releases ----------
class KnowledgeLibrary(Base):
    __tablename__ = "knowledge_libraries"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_knowledge_libraries_org_name"),
                      UniqueConstraint("organization_id", "id", name="uq_knowledge_libraries_org_id"),
                      CheckConstraint("status IN ('active', 'archived')", name="ck_knowledge_libraries_status"),
                      Index("ix_knowledge_libraries_org_status", "organization_id", "status"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String(20), nullable=False, default="active")
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    archived_at = Column(DateTime, nullable=True)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (ForeignKeyConstraint(["organization_id", "library_id"],
                                           ["knowledge_libraries.organization_id", "knowledge_libraries.id"]),
                      UniqueConstraint("organization_id", "id", name="uq_knowledge_documents_org_id"),
                      CheckConstraint("kind IN ('file', 'faq', 'manual')", name="ck_knowledge_documents_kind"),
                      CheckConstraint("status IN ('active', 'archived')", name="ck_knowledge_documents_status"),
                      Index("ix_knowledge_documents_org_library", "organization_id", "library_id"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    library_id = Column(String(36), nullable=False)
    kind = Column(String(20), nullable=False)
    title = Column(String(300), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    current_revision_id = Column(String(36), nullable=True)
    classification = Column(String(30), nullable=False, default="internal")
    retention_policy = Column(String(40), nullable=False, default="organization_default")
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    archived_at = Column(DateTime, nullable=True)


class KnowledgeDocumentRevision(Base):
    __tablename__ = "knowledge_document_revisions"
    __table_args__ = (ForeignKeyConstraint(["organization_id", "document_id"],
                                           ["knowledge_documents.organization_id", "knowledge_documents.id"]),
                      UniqueConstraint("document_id", "revision_no", name="uq_knowledge_revisions_number"),
                      UniqueConstraint("organization_id", "id", name="uq_knowledge_revisions_org_id"),
                      CheckConstraint("processing_state IN ('quarantined', 'uploaded', 'scanning', 'processing', "
                                      "'review_required', 'ready', 'failed', 'rejected')",
                                      name="ck_knowledge_revisions_processing_state"),
                      CheckConstraint("malware_state IN ('pending', 'clean', 'infected', 'error', 'not_applicable')",
                                      name="ck_knowledge_revisions_malware_state"),
                      Index("ix_knowledge_revisions_org_state", "organization_id", "processing_state"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    document_id = Column(String(36), nullable=False)
    revision_no = Column(Integer, nullable=False)
    source_kind = Column(String(20), nullable=False, default="file")
    original_filename = Column(String(300), nullable=True)
    declared_mime = Column(String(150), nullable=True)
    detected_mime = Column(String(150), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    sha256 = Column(String(64), nullable=True)
    storage_provider = Column(String(30), nullable=True)
    storage_key = Column(String(500), nullable=True)
    source_locale = Column(String(30), nullable=True)
    effective_from = Column(DateTime, nullable=True)
    effective_until = Column(DateTime, nullable=True)
    processing_state = Column(String(30), nullable=False, default="quarantined")
    malware_state = Column(String(20), nullable=False, default="pending")
    parser_name = Column(String(80), nullable=True)
    parser_version = Column(String(40), nullable=True)
    ocr_metadata = Column(JSON, nullable=False, default=dict)
    extracted_text_hash = Column(String(64), nullable=True)
    failure_code = Column(String(60), nullable=True)
    failure_detail = Column(String(300), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    ready_at = Column(DateTime, nullable=True)


class KnowledgeTextBlock(Base):
    __tablename__ = "knowledge_text_blocks"
    __table_args__ = (ForeignKeyConstraint(["organization_id", "revision_id"],
                                           ["knowledge_document_revisions.organization_id",
                                            "knowledge_document_revisions.id"]),
                      UniqueConstraint("revision_id", "ordinal", name="uq_knowledge_blocks_ordinal"),
                      Index("ix_knowledge_blocks_org_revision", "organization_id", "revision_id"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    revision_id = Column(String(36), nullable=False)
    ordinal = Column(Integer, nullable=False)
    block_type = Column(String(30), nullable=False)
    page_number = Column(Integer, nullable=True)
    section_path = Column(JSON, nullable=False, default=list)
    text = Column(Text, nullable=False)
    text_hash = Column(String(64), nullable=False)
    extraction_confidence = Column(Integer, nullable=True)
    source_metadata = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (ForeignKeyConstraint(["organization_id", "revision_id"],
                                           ["knowledge_document_revisions.organization_id",
                                            "knowledge_document_revisions.id"]),
                      UniqueConstraint("revision_id", "ordinal", name="uq_knowledge_chunks_ordinal"),
                      UniqueConstraint("organization_id", "id", name="uq_knowledge_chunks_org_id"),
                      Index("ix_knowledge_chunks_org_revision", "organization_id", "revision_id"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    revision_id = Column(String(36), nullable=False)
    block_id = Column(String(36), ForeignKey("knowledge_text_blocks.id"), nullable=True)
    ordinal = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=True)
    section_path = Column(JSON, nullable=False, default=list)
    content_hash = Column(String(64), nullable=False)
    chunker_name = Column(String(80), nullable=False)
    chunker_version = Column(String(40), nullable=False)
    search_terms = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=utcnow)


class KnowledgeEmbedding(Base):
    __tablename__ = "knowledge_embeddings"
    __table_args__ = (ForeignKeyConstraint(["organization_id", "chunk_id"],
                                           ["knowledge_chunks.organization_id", "knowledge_chunks.id"]),
                      UniqueConstraint("chunk_id", "model", "model_version", name="uq_knowledge_embeddings_model"),
                      Index("ix_knowledge_embeddings_org_chunk", "organization_id", "chunk_id"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    chunk_id = Column(String(36), nullable=False)
    provider = Column(String(40), nullable=False)
    model = Column(String(120), nullable=False)
    model_version = Column(String(60), nullable=False)
    dimensions = Column(Integer, nullable=False)
    vector_data = Column(JSON, nullable=False)  # Phase 4 migrates to pgvector only after approval/staging proof.
    created_at = Column(DateTime, nullable=False, default=utcnow)


class KnowledgeFaqEntry(Base):
    __tablename__ = "knowledge_faq_entries"
    __table_args__ = (ForeignKeyConstraint(["organization_id", "library_id"],
                                           ["knowledge_libraries.organization_id", "knowledge_libraries.id"]),
                      UniqueConstraint("organization_id", "id", name="uq_knowledge_faq_entries_org_id"),
                      Index("ix_knowledge_faq_entries_org_library", "organization_id", "library_id"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    library_id = Column(String(36), nullable=False)
    title = Column(String(300), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    current_revision_id = Column(String(36), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class KnowledgeFaqRevision(Base):
    __tablename__ = "knowledge_faq_revisions"
    __table_args__ = (ForeignKeyConstraint(["organization_id", "faq_entry_id"],
                                           ["knowledge_faq_entries.organization_id", "knowledge_faq_entries.id"]),
                      UniqueConstraint("faq_entry_id", "revision_no", name="uq_knowledge_faq_revisions_number"),
                      CheckConstraint("status IN ('draft', 'approved', 'superseded')",
                                      name="ck_knowledge_faq_revisions_status"),
                      Index("ix_knowledge_faq_revisions_org_entry", "organization_id", "faq_entry_id"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    faq_entry_id = Column(String(36), nullable=False)
    revision_no = Column(Integer, nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    aliases = Column(JSON, nullable=False, default=list)
    locale = Column(String(30), nullable=False, default="en-IN")
    effective_from = Column(DateTime, nullable=True)
    effective_until = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="draft")
    content_hash = Column(String(64), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    approved_at = Column(DateTime, nullable=True)


class KnowledgeJob(Base):
    __tablename__ = "knowledge_jobs"
    __table_args__ = (CheckConstraint("status IN ('queued', 'running', 'retry', 'completed', 'failed', 'cancelled')",
                                      name="ck_knowledge_jobs_status"),
                      Index("ix_knowledge_jobs_claim", "status", "next_attempt_at", "locked_until"),
                      Index("ix_knowledge_jobs_org_created", "organization_id", "created_at"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    revision_id = Column(String(36), ForeignKey("knowledge_document_revisions.id"), nullable=True)
    job_type = Column(String(40), nullable=False)
    status = Column(String(20), nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    next_attempt_at = Column(DateTime, nullable=False, default=utcnow)
    locked_until = Column(DateTime, nullable=True)
    locked_by = Column(String(100), nullable=True)
    progress = Column(JSON, nullable=False, default=dict)
    error_code = Column(String(60), nullable=True)
    last_error = Column(String(300), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    finished_at = Column(DateTime, nullable=True)


class KnowledgeSnapshot(Base):
    __tablename__ = "knowledge_snapshots"
    __table_args__ = (UniqueConstraint("organization_id", "manifest_hash", name="uq_knowledge_snapshots_manifest"),
                      UniqueConstraint("organization_id", "id", name="uq_knowledge_snapshots_org_id"),
                      Index("ix_knowledge_snapshots_org_created", "organization_id", "created_at"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False)
    agent_version_id = Column(String(36), ForeignKey("agent_versions.id"), nullable=False)
    manifest = Column(JSON, nullable=False)
    manifest_hash = Column(String(64), nullable=False)
    chunker_version = Column(String(80), nullable=False)
    embedding_model = Column(String(160), nullable=True)
    retrieval_policy_version = Column(String(80), nullable=False)
    item_count = Column(Integer, nullable=False)
    chunk_count = Column(Integer, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class KnowledgeSnapshotItem(Base):
    __tablename__ = "knowledge_snapshot_items"
    __table_args__ = (ForeignKeyConstraint(["organization_id", "snapshot_id"],
                                           ["knowledge_snapshots.organization_id", "knowledge_snapshots.id"]),
                      ForeignKeyConstraint(["organization_id", "revision_id"],
                                           ["knowledge_document_revisions.organization_id",
                                            "knowledge_document_revisions.id"]),
                      UniqueConstraint("snapshot_id", "revision_id", name="uq_knowledge_snapshot_items_revision"),
                      Index("ix_knowledge_snapshot_items_org_snapshot", "organization_id", "snapshot_id"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    snapshot_id = Column(String(36), nullable=False)
    revision_id = Column(String(36), nullable=False)
    ordinal = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    extracted_text_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class AgentVersionKnowledgeItem(Base):
    __tablename__ = "agent_version_knowledge_items"
    __table_args__ = (ForeignKeyConstraint(["organization_id", "revision_id"],
                                           ["knowledge_document_revisions.organization_id",
                                            "knowledge_document_revisions.id"]),
                      UniqueConstraint("agent_version_id", "revision_id", name="uq_agent_version_knowledge_revision"),
                      Index("ix_agent_version_knowledge_org_version", "organization_id", "agent_version_id"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    agent_version_id = Column(String(36), ForeignKey("agent_versions.id"), nullable=False)
    revision_id = Column(String(36), nullable=False)
    priority = Column(Integer, nullable=False, default=0)
    locale = Column(String(30), nullable=True)
    tags = Column(JSON, nullable=False, default=list)
    ordinal = Column(Integer, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class AgentValidationRun(Base):
    __tablename__ = "agent_validation_runs"
    __table_args__ = (CheckConstraint("status IN ('queued', 'running', 'passed', 'failed', 'error')",
                                      name="ck_agent_validation_runs_status"),
                      Index("ix_agent_validation_runs_org_version", "organization_id", "agent_version_id"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    agent_version_id = Column(String(36), ForeignKey("agent_versions.id"), nullable=False)
    validator_version = Column(String(80), nullable=False)
    status = Column(String(20), nullable=False, default="queued")
    findings = Column(JSON, nullable=False, default=list)
    golden_total = Column(Integer, nullable=False, default=0)
    golden_passed = Column(Integer, nullable=False, default=0)
    started_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    started_at = Column(DateTime, nullable=False, default=utcnow)
    completed_at = Column(DateTime, nullable=True)


class ProviderConnection(Base):
    __tablename__ = "provider_connections"
    __table_args__ = (UniqueConstraint("organization_id", "provider", "workspace_reference",
                                      name="uq_provider_connections_workspace"),
                      Index("ix_provider_connections_org_provider", "organization_id", "provider"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    provider = Column(String(30), nullable=False)
    organization_reference = Column(String(200), nullable=True)
    workspace_reference = Column(String(200), nullable=False)
    secret_reference = Column(String(300), nullable=True)
    capabilities = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="unverified")
    verified_at = Column(DateTime, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class ProviderSync(Base):
    __tablename__ = "provider_syncs"
    __table_args__ = (UniqueConstraint("organization_id", "idempotency_key", name="uq_provider_syncs_idempotency"),
                      CheckConstraint("status IN ('pending', 'running', 'attestation_required', 'synced', "
                                      "'failed', 'cancelled')", name="ck_provider_syncs_status"),
                      Index("ix_provider_syncs_org_version", "organization_id", "agent_version_id"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    agent_version_id = Column(String(36), ForeignKey("agent_versions.id"), nullable=False)
    knowledge_snapshot_id = Column(String(36), ForeignKey("knowledge_snapshots.id"), nullable=True)
    connection_id = Column(String(36), ForeignKey("provider_connections.id"), nullable=True)
    provider = Column(String(30), nullable=False)
    mode = Column(String(30), nullable=False)
    status = Column(String(30), nullable=False, default="pending")
    provider_app_id = Column(String(200), nullable=True)
    provider_app_version = Column(Integer, nullable=True)
    provider_kb_references = Column(JSON, nullable=False, default=list)
    desired_manifest_hash = Column(String(64), nullable=False)
    observed_manifest_hash = Column(String(64), nullable=True)
    idempotency_key = Column(String(100), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    error_code = Column(String(60), nullable=True)
    last_error = Column(String(300), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    synced_at = Column(DateTime, nullable=True)


class RetrievalCredential(Base):
    __tablename__ = "retrieval_credentials"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_retrieval_credentials_hash"),
                      Index("ix_retrieval_credentials_org_snapshot", "organization_id", "knowledge_snapshot_id"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    agent_version_id = Column(String(36), ForeignKey("agent_versions.id"), nullable=False)
    knowledge_snapshot_id = Column(String(36), ForeignKey("knowledge_snapshots.id"), nullable=False)
    token_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    expires_at = Column(DateTime, nullable=True)
    rotated_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class KnowledgeRetrievalEvent(Base):
    __tablename__ = "knowledge_retrieval_events"
    __table_args__ = (Index("ix_knowledge_retrieval_events_org_created", "organization_id", "created_at"),
                      Index("ix_knowledge_retrieval_events_snapshot", "knowledge_snapshot_id", "created_at"))
    id = Column(String(36), primary_key=True, default=new_id)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("training_sessions.id"), nullable=True)
    agent_version_id = Column(String(36), ForeignKey("agent_versions.id"), nullable=False)
    knowledge_snapshot_id = Column(String(36), ForeignKey("knowledge_snapshots.id"), nullable=False)
    query_hash = Column(String(64), nullable=False)
    selected_chunk_ids = Column(JSON, nullable=False, default=list)
    latency_ms = Column(Integer, nullable=True)
    result_count = Column(Integer, nullable=False, default=0)
    outcome = Column(String(30), nullable=False)
    error_code = Column(String(60), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class ImmutableKnowledgeArtifact(Exception):
    """Raised when application code tries to rewrite content that an immutable release may reference."""


def _block_immutable_knowledge_update(mapper, connection, target):
    state = inspect(target)
    if isinstance(target, KnowledgeDocumentRevision):
        history = state.attrs.processing_state.history
        previous = history.deleted[0] if history.deleted else target.processing_state
        immutable = previous == "ready"
    elif isinstance(target, KnowledgeFaqRevision):
        history = state.attrs.status.history
        previous = history.deleted[0] if history.deleted else target.status
        immutable = previous in ("approved", "superseded")
    else:
        immutable = state.persistent
    if immutable:
        raise ImmutableKnowledgeArtifact(f"{target.__tablename__} artifact cannot be changed")


def _block_immutable_knowledge_delete(mapper, connection, target):
    if isinstance(target, KnowledgeDocumentRevision) and target.processing_state != "ready":
        return
    if isinstance(target, KnowledgeFaqRevision) and target.status == "draft":
        return
    raise ImmutableKnowledgeArtifact(f"{target.__tablename__} artifact cannot be deleted")


for _immutable_model in (KnowledgeDocumentRevision, KnowledgeTextBlock, KnowledgeChunk, KnowledgeEmbedding,
                         KnowledgeFaqRevision, KnowledgeSnapshot, KnowledgeSnapshotItem):
    event.listen(_immutable_model, "before_update", _block_immutable_knowledge_update)
    event.listen(_immutable_model, "before_delete", _block_immutable_knowledge_delete)
