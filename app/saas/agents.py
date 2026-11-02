"""Voice agent registry for the training SaaS: teams, agents, immutable versions, scenarios and assignments.

Agents are hosted at Sarvam. An agent here is a link to an app built in Sarvam: we store its app id,
and each published version records the exact Sarvam app version it uses. The optional read-only MCP
connection imports agent metadata; creation, editing and publishing at Sarvam remain out of scope.
"""
import base64
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import event, func, inspect, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import utcnow
from .auth import OrgContext, audit, get_db, org_access, scoped_get
from .models import (Agent, AgentAssignment, AgentVersion, Membership, Team, TeamMember, TraineeAgentTrainingProfile,
                     TrainingScenario, TrainingSession, TrainingTranscript, TrainingTranscriptTurn, User)
from .permissions import ADMIN, RANK, can_assign_to

PROVIDERS = ("sarvam",)
CHANNELS = ("phone", "browser")
DIFFICULTIES = ("beginner", "intermediate", "advanced")
SCENARIO_STATUSES = ("draft", "active", "archived")
VARIABLE_TYPES = ("string", "number", "integer", "boolean", "enum")
VAR_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")
APP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
SECRET_KEY_RE = re.compile(r"(api[_-]?key|secret|token|password|credential)", re.I)
MAX_JSON = 20000
MAX_BULK = 200


# ---------- published versions never change ----------
IMMUTABLE_VERSION_FIELDS = ("organization_id", "agent_id", "internal_version", "provider_app_version",
                            "configuration_snapshot", "variable_schema", "knowledge_base_reference",
                            "rubric_reference", "notes", "behavior_snapshot", "knowledge_snapshot_id",
                            "provider_sync_id", "validation_report_id", "release_state", "content_hash",
                            "status", "published_at", "published_by")


class PublishedVersionImmutable(Exception):
    pass


@event.listens_for(AgentVersion, "before_update")
def _guard_published_update(mapper, connection, target):
    """Last line of defence under the API checks: an UPDATE of a version that was already published
    raises instead of reaching the database."""
    state = inspect(target)
    status = state.attrs.status.history
    was = (status.deleted or status.unchanged or [None])[0]
    if was != "published":
        return
    changed = [f for f in IMMUTABLE_VERSION_FIELDS if state.attrs[f].history.has_changes()]
    if changed:
        raise PublishedVersionImmutable(f"published agent version {target.id} cannot change: {', '.join(changed)}")


@event.listens_for(AgentVersion, "before_delete")
def _guard_published_delete(mapper, connection, target):
    if inspect(target).attrs.status.history.unchanged == ["published"] or target.status == "published":
        raise PublishedVersionImmutable(f"published agent version {target.id} cannot be deleted")


# ---------- validation ----------
def to_utc(dt: datetime | None) -> datetime | None:
    """Stored datetimes are naive UTC. Accepts aware values (converted) or naive ones (taken as UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _json_size_ok(value) -> bool:
    return len(repr(value)) <= MAX_JSON


def schema_problems(schema) -> list[str]:
    """Checks a variable schema: a list of {name, type, required?, description?, options?, max_length?,
    min?, max?, default?}."""
    if not isinstance(schema, list):
        return ["Variable schema must be a list."]
    if len(schema) > 50:
        return ["At most 50 variables."]
    problems, seen = [], set()
    for i, v in enumerate(schema):
        where = f"Variable {i + 1}"
        if not isinstance(v, dict):
            problems.append(f"{where} must be an object.")
            continue
        unknown = set(v) - {"name", "type", "required", "description", "options", "max_length", "min", "max", "default"}
        if unknown:
            problems.append(f"{where} has unknown fields: {', '.join(sorted(unknown))}.")
        name = v.get("name")
        if not isinstance(name, str) or not VAR_NAME_RE.match(name):
            problems.append(f"{where}: name must be lower-case letters, digits and underscores.")
            continue
        where = f"Variable '{name}'"
        if name in seen:
            problems.append(f"{where} is defined twice.")
        seen.add(name)
        t = v.get("type")
        if t not in VARIABLE_TYPES:
            problems.append(f"{where}: type must be one of {', '.join(VARIABLE_TYPES)}.")
            continue
        if "required" in v and not isinstance(v["required"], bool):
            problems.append(f"{where}: required must be true or false.")
        if "description" in v and (not isinstance(v["description"], str) or len(v["description"]) > 500):
            problems.append(f"{where}: description must be text up to 500 characters.")
        if t == "enum":
            opts = v.get("options")
            if (not isinstance(opts, list) or not 1 <= len(opts) <= 50
                    or not all(isinstance(o, str) and 0 < len(o) <= 200 for o in opts) or len(set(opts)) != len(opts)):
                problems.append(f"{where}: an enum needs 1 to 50 distinct text options.")
        elif "options" in v:
            problems.append(f"{where}: options are only for enum variables.")
        if "max_length" in v and (t != "string" or not isinstance(v["max_length"], int)
                                  or isinstance(v["max_length"], bool) or not 1 <= v["max_length"] <= 5000):
            problems.append(f"{where}: max_length is for string variables, between 1 and 5000.")
        for bound in ("min", "max"):
            if bound in v and (t not in ("number", "integer") or not _is_number(v[bound])):
                problems.append(f"{where}: {bound} is for number variables and must be a number.")
        if "default" in v:
            err = value_problem(v, v["default"])
            if err:
                problems.append(f"{where}: default {err}")
    return problems


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def value_problem(var: dict, value) -> str | None:
    t = var.get("type")
    if t == "string":
        if not isinstance(value, str):
            return "must be text."
        if len(value) > var.get("max_length", 2000):
            return f"must be at most {var.get('max_length', 2000)} characters."
    elif t == "number":
        if not _is_number(value):
            return "must be a number."
    elif t == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return "must be a whole number."
    elif t == "boolean":
        if not isinstance(value, bool):
            return "must be true or false."
    elif t == "enum":
        if value not in (var.get("options") or []):
            return "must be one of the listed options."
    if t in ("number", "integer") and _is_number(value):
        if "min" in var and value < var["min"]:
            return f"must be at least {var['min']}."
        if "max" in var and value > var["max"]:
            return f"must be at most {var['max']}."
    return None


def variables_problems(schema: list, values, require_all: bool) -> list[str]:
    """Checks scenario variables against an agent version's schema. require_all also demands every
    required variable that has no default."""
    if not isinstance(values, dict):
        return ["Agent variables must be an object."]
    by_name = {v["name"]: v for v in schema if isinstance(v, dict) and "name" in v}
    problems = [f"'{k}' is not a variable of this agent." for k in values if k not in by_name]
    for k, val in values.items():
        if k in by_name:
            err = value_problem(by_name[k], val)
            if err:
                problems.append(f"'{k}' {err}")
    if require_all:
        problems += [f"'{n}' is required." for n, v in by_name.items()
                     if v.get("required") and "default" not in v and n not in values]
    return problems


def config_problems(config) -> list[str]:
    if not isinstance(config, dict):
        return ["Configuration must be an object."]
    if not _json_size_ok(config):
        return ["Configuration is too large."]
    problems = []

    def walk(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if not isinstance(k, str):
                    problems.append(f"Configuration keys must be text ({path}).")
                elif SECRET_KEY_RE.search(k):
                    problems.append(f"Do not store credentials in the configuration ('{path}{k}'). "
                                    "Provider keys stay in the server settings.")
                walk(v, f"{path}{k}.")
        elif isinstance(obj, list):
            for x in obj:
                walk(x, path)
    walk(config, "")
    for key in ("connection_id", "agent_phone_number", "language", "voice"):
        if key in config and (not isinstance(config[key], str) or len(config[key]) > 200):
            problems.append(f"'{key}' must be text up to 200 characters.")
    return problems


def publish_problems(agent: Agent, v: AgentVersion) -> list[str]:
    problems = []
    if agent.status != "active":
        problems.append("Archived agents cannot publish versions.")
    if not agent.provider_app_id:
        problems.append("The agent needs a provider app id.")
    if not agent.channels:
        problems.append("Choose at least one training channel for the agent.")
    pav = v.provider_app_version
    if not isinstance(pav, int) or isinstance(pav, bool) or pav < 1:
        problems.append("Enter the Sarvam app version this version uses (a whole number, 1 or more).")
    problems += config_problems(v.configuration_snapshot)
    problems += schema_problems(v.variable_schema)
    return problems


# ---------- response shapes ----------
def agent_out(a: Agent, published: AgentVersion | None = None, draft: AgentVersion | None = None) -> dict:
    out = {"id": a.id, "name": a.name, "description": a.description, "category": a.category,
           "provider": a.provider, "provider_app_id": a.provider_app_id, "channels": a.channels or [],
           "status": a.status, "published_version_id": a.published_version_id,
           "created_at": iso(a.created_at), "updated_at": iso(a.updated_at), "archived_at": iso(a.archived_at)}
    if published is not None or draft is not None:
        out["published_version"] = version_out(published) if published else None
        out["draft_version"] = version_out(draft) if draft else None
    return out


def version_out(v: AgentVersion) -> dict:
    return {"id": v.id, "agent_id": v.agent_id, "internal_version": v.internal_version,
            "provider_app_version": v.provider_app_version, "configuration_snapshot": v.configuration_snapshot or {},
            "variable_schema": v.variable_schema or [], "knowledge_base_reference": v.knowledge_base_reference,
            "rubric_reference": v.rubric_reference, "notes": v.notes, "status": v.status,
            "behavior_snapshot": v.behavior_snapshot or {}, "knowledge_snapshot_id": v.knowledge_snapshot_id,
            "provider_sync_id": v.provider_sync_id, "validation_report_id": v.validation_report_id,
            "release_state": v.release_state, "content_hash": v.content_hash,
            "based_on_version_id": v.based_on_version_id, "created_by": v.created_by,
            "published_at": iso(v.published_at), "published_by": v.published_by,
            "created_at": iso(v.created_at), "updated_at": iso(v.updated_at)}


def scenario_out(s: TrainingScenario) -> dict:
    return {"id": s.id, "agent_id": s.agent_id, "name": s.name, "description": s.description,
            "difficulty": s.difficulty, "persona": s.persona, "objective": s.objective,
            "opening_context": s.opening_context, "expected_behavior": s.expected_behavior,
            "evaluation_criteria_reference": s.evaluation_criteria_reference,
            "agent_variables": s.agent_variables or {}, "validated_version_id": s.validated_version_id,
            "rubric_id": s.rubric_id, "status": s.status, "created_at": iso(s.created_at), "updated_at": iso(s.updated_at),
            "archived_at": iso(s.archived_at)}


def assignment_state(a: AgentAssignment, now: datetime) -> str:
    if a.revoked_at is not None:
        return "revoked" if a.revoke_reason != "replaced" else "replaced"
    if a.expires_at is not None and a.expires_at <= now:
        return "expired"
    if a.starts_at > now:
        return "scheduled"
    return "active"


def assignment_out(a: AgentAssignment, now: datetime, names: dict | None = None) -> dict:
    names = names or {}
    return {"id": a.id, "agent_id": a.agent_id, "agent_name": names.get(("agent", a.agent_id)),
            "user_id": a.user_id, "user_email": names.get(("user", a.user_id)),
            "team_id": a.team_id, "team_name": names.get(("team", a.team_id)),
            "assigned_by": a.assigned_by, "starts_at": iso(a.starts_at), "expires_at": iso(a.expires_at),
            "revoked_at": iso(a.revoked_at), "revoked_by": a.revoked_by, "revoke_reason": a.revoke_reason,
            "settings": a.settings or {}, "state": assignment_state(a, now), "created_at": iso(a.created_at)}


def team_out(t: Team, member_count: int | None = None) -> dict:
    out = {"id": t.id, "name": t.name, "description": t.description, "status": t.status,
           "created_at": iso(t.created_at), "archived_at": iso(t.archived_at)}
    if member_count is not None:
        out["member_count"] = member_count
    return out


def page(items: list, total: int, limit: int, offset: int) -> dict:
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def clamp_page(limit: int, offset: int) -> tuple[int, int]:
    return min(max(limit, 1), 200), max(offset, 0)


# ---------- assignment resolution ----------
def _open(model, now):
    """SQL condition: an assignment that is not revoked, has started and has not expired."""
    return (model.revoked_at.is_(None), model.starts_at <= now,
            or_(model.expires_at.is_(None), model.expires_at > now))


def active_team_ids(db: Session, org_id: str, user_id: str) -> list[str]:
    return list(db.scalars(select(TeamMember.team_id).join(Team, Team.id == TeamMember.team_id).where(
        TeamMember.organization_id == org_id, TeamMember.user_id == user_id, TeamMember.removed_at.is_(None),
        Team.status == "active")))


@dataclass
class Entitlement:
    """What one user may do with one agent, combined from their direct and team assignments."""
    agent: Agent
    version: AgentVersion
    assignments: list = field(default_factory=list)
    source: str = "team"  # direct | team
    allowed_scenario_ids: list | None = None  # None = every active scenario of the agent
    max_sessions: int | None = None
    max_minutes_per_session: int | None = None
    expires_at: datetime | None = None


def _combine(agent: Agent, version: AgentVersion, rows: list[AgentAssignment]) -> Entitlement:
    """Rules (documented in docs/ARCHITECTURE.md):
    - A direct assignment, when there is one, decides everything; team assignments are ignored.
    - Otherwise team assignments add up: allowed scenarios are the union (any team allowing all means
      all), limits take the most generous value (no limit beats any limit), expiry is the latest.
    """
    direct = [a for a in rows if a.user_id is not None]
    use = direct or rows
    ent = Entitlement(agent=agent, version=version, assignments=use, source="direct" if direct else "team")
    scen, all_scen = set(), False
    sessions, minutes = [], []
    expiries = []
    for a in use:
        s = a.settings or {}
        ids = s.get("allowed_scenario_ids")
        if ids is None:
            all_scen = True
        else:
            scen.update(ids)
        sessions.append(s.get("max_sessions"))
        minutes.append(s.get("max_minutes_per_session"))
        expiries.append(a.expires_at)
    ent.allowed_scenario_ids = None if all_scen else sorted(scen)
    ent.max_sessions = None if None in sessions else max(sessions)
    ent.max_minutes_per_session = None if None in minutes else max(minutes)
    ent.expires_at = None if None in expiries else max(expiries)
    return ent


def entitlements(db: Session, org_id: str, user_id: str, agent_id: str | None = None) -> list[Entitlement]:
    """Every agent the user may train with right now. The caller must already have checked the user's
    active membership of org_id (org_access does). Archived agents and agents with no published version
    are left out."""
    now = utcnow()
    teams = active_team_ids(db, org_id, user_id)
    target = AgentAssignment.user_id == user_id
    if teams:
        target = or_(target, AgentAssignment.team_id.in_(teams))
    q = select(AgentAssignment).where(AgentAssignment.organization_id == org_id, target, *_open(AgentAssignment, now))
    if agent_id:
        q = q.where(AgentAssignment.agent_id == agent_id)
    rows = db.scalars(q).all()
    by_agent: dict[str, list] = {}
    for a in rows:
        by_agent.setdefault(a.agent_id, []).append(a)
    if not by_agent:
        return []
    agents = db.scalars(select(Agent).where(Agent.organization_id == org_id, Agent.id.in_(by_agent),
                                            Agent.status == "active", Agent.published_version_id.is_not(None))).all()
    out = []
    for ag in sorted(agents, key=lambda x: x.name.lower()):
        v = db.get(AgentVersion, ag.published_version_id)
        if v is None or v.status != "published" or v.organization_id != org_id:
            continue
        out.append(_combine(ag, v, by_agent[ag.id]))
    return out


def allowed_scenarios(db: Session, ent: Entitlement) -> list[TrainingScenario]:
    q = select(TrainingScenario).where(TrainingScenario.organization_id == ent.agent.organization_id,
                                       TrainingScenario.agent_id == ent.agent.id,
                                       TrainingScenario.status == "active")
    if ent.allowed_scenario_ids is not None:
        if not ent.allowed_scenario_ids:
            return []
        q = q.where(TrainingScenario.id.in_(ent.allowed_scenario_ids))
    return list(db.scalars(q.order_by(TrainingScenario.name)))


class NotEntitled(Exception):
    pass


@dataclass(frozen=True)
class TrainingTarget:
    """Everything a future training session needs to start, resolved on the server:
    organization -> assigned agent -> published version -> provider app id/version -> channel."""
    organization_id: str
    user_id: str
    agent_id: str
    agent_version_id: str
    provider: str
    provider_app_id: str
    provider_app_version: int
    channel: str
    scenario_id: str | None
    agent_variables: dict
    configuration: dict

    def call_target(self, settings):
        """The CallTarget for the phone channel. Connection and number come from the version's
        configuration, falling back to the platform's default Sarvam connection."""
        from ..integrations import CallTarget
        return CallTarget(app_id=self.provider_app_id, app_version=self.provider_app_version,
                          connection_id=self.configuration.get("connection_id") or settings.sarvam_connection_id,
                          agent_phone=self.configuration.get("agent_phone_number") or settings.sarvam_agent_phone)


def resolve_training_target(db: Session, org_id: str, user_id: str, agent_id: str, channel: str,
                            scenario_id: str | None = None) -> TrainingTarget:
    """Server-side check used by Phase 3 before any session starts. Raises NotEntitled when the user has
    no open assignment, the channel is not offered, or the scenario is not allowed. Calls nobody."""
    m = db.scalars(select(Membership).where(Membership.organization_id == org_id, Membership.user_id == user_id,
                                            Membership.status == "active")).first()
    if m is None:
        raise NotEntitled("not a member of this organization")
    ents = entitlements(db, org_id, user_id, agent_id)
    if not ents:
        raise NotEntitled("no open assignment for this agent")
    ent = ents[0]
    if channel not in (ent.agent.channels or []):
        raise NotEntitled(f"the agent does not offer the {channel} channel")
    variables = {}
    if scenario_id is not None:
        allowed = {s.id: s for s in allowed_scenarios(db, ent)}
        if scenario_id not in allowed:
            raise NotEntitled("scenario not allowed")
        variables = dict(allowed[scenario_id].agent_variables or {})
    defaults = {v["name"]: v["default"] for v in ent.version.variable_schema or [] if "default" in v}
    return TrainingTarget(organization_id=org_id, user_id=user_id, agent_id=ent.agent.id,
                          agent_version_id=ent.version.id, provider=ent.agent.provider,
                          provider_app_id=ent.agent.provider_app_id,
                          provider_app_version=ent.version.provider_app_version, channel=channel,
                          scenario_id=scenario_id, agent_variables={**defaults, **variables},
                          configuration=dict(ent.version.configuration_snapshot or {}))


# ---------- request bodies ----------
class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class TeamPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class TeamMembersIn(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=MAX_BULK)


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    category: str = Field(default="", max_length=80)
    provider: str = "sarvam"
    provider_app_id: str = Field(min_length=1, max_length=200)
    channels: list[str] = Field(default_factory=lambda: ["phone"], max_length=len(CHANNELS))
    provider_app_version: int | None = Field(default=None, ge=1)
    variable_schema: list = Field(default_factory=list, max_length=50)


class AgentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(default=None, max_length=80)
    provider_app_id: str | None = Field(default=None, min_length=1, max_length=200)
    channels: list[str] | None = Field(default=None, max_length=len(CHANNELS))


class NewDraftIn(BaseModel):
    based_on_version_id: str | None = Field(default=None, max_length=36)


class VersionPatch(BaseModel):
    provider_app_version: int | None = Field(default=None, ge=1)
    configuration_snapshot: dict | None = None
    variable_schema: list | None = None
    knowledge_base_reference: str | None = Field(default=None, max_length=500)
    rubric_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=5000)


class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    difficulty: str = "beginner"
    persona: str = Field(default="", max_length=5000)
    objective: str = Field(default="", max_length=5000)
    opening_context: str = Field(default="", max_length=5000)
    expected_behavior: str = Field(default="", max_length=5000)
    evaluation_criteria_reference: str = Field(default="", max_length=500)
    agent_variables: dict = Field(default_factory=dict)
    status: str = "draft"


class ScenarioPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    difficulty: str | None = None
    persona: str | None = Field(default=None, max_length=5000)
    objective: str | None = Field(default=None, max_length=5000)
    opening_context: str | None = Field(default=None, max_length=5000)
    expected_behavior: str | None = Field(default=None, max_length=5000)
    evaluation_criteria_reference: str | None = Field(default=None, max_length=500)
    agent_variables: dict | None = None
    status: str | None = None


class AssignmentSettings(BaseModel):
    allowed_scenario_ids: list[str] | None = Field(default=None, max_length=200)
    max_sessions: int | None = Field(default=None, ge=1, le=10000)
    max_minutes_per_session: int | None = Field(default=None, ge=1, le=180)


class MyTrainingProfileIn(BaseModel):
    instructions: str = Field(default="", max_length=10_000)
    variable_values: dict = Field(default_factory=dict)


class MyTrainingTextIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=30_000)


class MyTrainingPdfIn(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(min_length=1, max_length=7_000_000)


class MyTrainingTranscriptIn(BaseModel):
    session_id: str = Field(max_length=36)


class AssignIn(BaseModel):
    agent_ids: list[str] = Field(min_length=1, max_length=50)
    user_ids: list[str] = Field(default_factory=list, max_length=MAX_BULK)
    team_ids: list[str] = Field(default_factory=list, max_length=MAX_BULK)
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    settings: AssignmentSettings = Field(default_factory=AssignmentSettings)


class AssignmentPatch(BaseModel):
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    clear_expiry: bool = False
    settings: AssignmentSettings | None = None


def build_agents_router() -> APIRouter:
    r = APIRouter(prefix="/api/v1/organizations/{org_id}")

    def unprocessable(problems: list[str]):
        raise HTTPException(status_code=422, detail=" ".join(problems))

    def check_channels(channels: list[str]):
        bad = [c for c in channels if c not in CHANNELS]
        if bad or len(set(channels)) != len(channels):
            raise HTTPException(status_code=422, detail=f"Channels must be chosen from: {', '.join(CHANNELS)}.")

    def check_app_id(app_id: str) -> str:
        app_id = app_id.strip()
        if not APP_ID_RE.match(app_id):
            raise HTTPException(status_code=422, detail="Provider app id: letters, digits, dot, dash, colon or underscore.")
        return app_id

    def agent_for(db: Session, ctx: OrgContext, agent_id: str) -> Agent:
        return scoped_get(db, Agent, ctx.org.id, agent_id)

    def version_for(db: Session, agent: Agent, version_id: str) -> AgentVersion:
        v = db.scalars(select(AgentVersion).where(AgentVersion.id == version_id, AgentVersion.agent_id == agent.id,
                                                  AgentVersion.organization_id == agent.organization_id)).first()
        if v is None:
            raise HTTPException(status_code=404, detail="Not found.")
        return v

    def draft_of(db: Session, agent: Agent) -> AgentVersion | None:
        return db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent.id,
                                                     AgentVersion.status == "draft")).first()

    def next_number(db: Session, agent: Agent) -> int:
        return (db.scalar(select(func.max(AgentVersion.internal_version)).where(
            AgentVersion.agent_id == agent.id)) or 0) + 1

    def commit_or_conflict(db: Session, message: str):
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail=message)

    # ---------- teams ----------
    @r.get("/teams")
    def list_teams(include_archived: bool = False, ctx: OrgContext = Depends(org_access("teams.view")),
                   db: Session = Depends(get_db)):
        q = select(Team).where(Team.organization_id == ctx.org.id)
        if not include_archived:
            q = q.where(Team.status == "active")
        counts = dict(db.execute(select(TeamMember.team_id, func.count(TeamMember.id)).where(
            TeamMember.organization_id == ctx.org.id, TeamMember.removed_at.is_(None)).group_by(TeamMember.team_id)).all())
        return [team_out(t, counts.get(t.id, 0)) for t in db.scalars(q.order_by(Team.name))]

    @r.post("/teams", status_code=201)
    def create_team(body: TeamIn, request: Request, ctx: OrgContext = Depends(org_access("teams.manage")),
                    db: Session = Depends(get_db)):
        t = Team(organization_id=ctx.org.id, name=body.name.strip(), description=body.description,
                 status="active", created_by=ctx.user.id)
        db.add(t)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="A team with that name already exists.")
        audit(db, request, "team.created", actor=ctx.user, organization_id=ctx.org.id, target_type="team",
              target_id=t.id, details={"name": t.name})
        commit_or_conflict(db, "A team with that name already exists.")
        return team_out(t, 0)

    @r.patch("/teams/{team_id}")
    def update_team(team_id: str, body: TeamPatch, request: Request,
                    ctx: OrgContext = Depends(org_access("teams.manage")), db: Session = Depends(get_db)):
        t = scoped_get(db, Team, ctx.org.id, team_id)
        if body.name is not None:
            t.name = body.name.strip()
        if body.description is not None:
            t.description = body.description
        audit(db, request, "team.updated", actor=ctx.user, organization_id=ctx.org.id, target_type="team",
              target_id=t.id, details=body.model_dump(exclude_none=True))
        commit_or_conflict(db, "A team with that name already exists.")
        return team_out(t)

    @r.post("/teams/{team_id}/archive")
    def archive_team(team_id: str, request: Request, ctx: OrgContext = Depends(org_access("teams.manage")),
                     db: Session = Depends(get_db)):
        t = scoped_get(db, Team, ctx.org.id, team_id)
        if t.status != "archived":
            t.status, t.archived_at = "archived", utcnow()
            audit(db, request, "team.archived", actor=ctx.user, organization_id=ctx.org.id, target_type="team",
                  target_id=t.id)
            db.commit()
        return team_out(t)

    @r.get("/teams/{team_id}/members")
    def list_team_members(team_id: str, ctx: OrgContext = Depends(org_access("teams.view")),
                          db: Session = Depends(get_db)):
        t = scoped_get(db, Team, ctx.org.id, team_id)
        rows = db.execute(select(TeamMember, User).join(User, User.id == TeamMember.user_id).where(
            TeamMember.team_id == t.id, TeamMember.removed_at.is_(None)).order_by(User.email)).all()
        return [{"user_id": u.id, "email": u.email, "name": u.name, "added_at": iso(tm.created_at)} for tm, u in rows]

    @r.post("/teams/{team_id}/members")
    def add_team_members(team_id: str, body: TeamMembersIn, request: Request,
                         ctx: OrgContext = Depends(org_access("teams.manage")), db: Session = Depends(get_db)):
        t = scoped_get(db, Team, ctx.org.id, team_id)
        if t.status != "active":
            raise HTTPException(status_code=409, detail="This team is archived.")
        ids = list(dict.fromkeys(body.user_ids))
        members = set(db.scalars(select(Membership.user_id).where(
            Membership.organization_id == ctx.org.id, Membership.status == "active", Membership.user_id.in_(ids))))
        if members != set(ids):
            raise HTTPException(status_code=404, detail="One or more people are not members of this organization.")
        current = set(db.scalars(select(TeamMember.user_id).where(TeamMember.team_id == t.id,
                                                                 TeamMember.removed_at.is_(None))))
        added = [u for u in ids if u not in current]
        for u in added:
            db.add(TeamMember(organization_id=ctx.org.id, team_id=t.id, user_id=u, added_by=ctx.user.id))
        if added:
            audit(db, request, "team.members_added", actor=ctx.user, organization_id=ctx.org.id, target_type="team",
                  target_id=t.id, details={"user_ids": added})
        commit_or_conflict(db, "Someone was added at the same time. Try again.")
        return {"added": added, "already_members": [u for u in ids if u in current]}

    @r.delete("/teams/{team_id}/members/{user_id}")
    def remove_team_member(team_id: str, user_id: str, request: Request,
                           ctx: OrgContext = Depends(org_access("teams.manage")), db: Session = Depends(get_db)):
        t = scoped_get(db, Team, ctx.org.id, team_id)
        tm = db.scalars(select(TeamMember).where(TeamMember.team_id == t.id, TeamMember.user_id == user_id,
                                                 TeamMember.removed_at.is_(None))).first()
        if tm is None:
            raise HTTPException(status_code=404, detail="Not found.")
        tm.removed_at = utcnow()
        audit(db, request, "team.member_removed", actor=ctx.user, organization_id=ctx.org.id, target_type="team",
              target_id=t.id, details={"user_id": user_id})
        db.commit()
        return {"ok": True}

    # ---------- agents ----------
    @r.get("/integrations/sarvam/status")
    def sarvam_status(request: Request, ctx: OrgContext = Depends(org_access("agents.manage"))):
        from .sarvam_mcp import connection_status
        s = request.app.state.settings
        return connection_status(ctx.org, s.sarvam_mcp_encryption_key)

    @r.post("/integrations/sarvam/connect")
    def connect_sarvam(request: Request, ctx: OrgContext = Depends(org_access("agents.manage")),
                       db: Session = Depends(get_db)):
        from .sarvam_mcp import SarvamMCPError, begin
        s = request.app.state.settings
        base = s.public_base_url or str(request.base_url).rstrip("/")
        callback_url = f"{base}/api/v1/organizations/{ctx.org.id}/integrations/sarvam/callback"
        try:
            authorization_url = begin(ctx.org, s.sarvam_mcp_encryption_key, s.sarvam_mcp_url, callback_url)
        except SarvamMCPError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        audit(db, request, "sarvam.connection_started", actor=ctx.user, organization_id=ctx.org.id,
              target_type="organization", target_id=ctx.org.id)
        db.commit()
        return {"authorization_url": authorization_url}

    @r.get("/integrations/sarvam/callback")
    def sarvam_callback(request: Request, code: str = "", state: str = "", error: str = "",
                        ctx: OrgContext = Depends(org_access("agents.manage")), db: Session = Depends(get_db)):
        from .sarvam_mcp import SarvamMCPError, callback
        s = request.app.state.settings
        target = f"{s.app_url()}/agents/new/" if s.app_url() else "/app/agents/new/"
        if error:
            return RedirectResponse(f"{target}?sarvam=error")
        try:
            callback(ctx.org, s.sarvam_mcp_encryption_key, code, state)
        except SarvamMCPError:
            return RedirectResponse(f"{target}?sarvam=error")
        audit(db, request, "sarvam.connected", actor=ctx.user, organization_id=ctx.org.id,
              target_type="organization", target_id=ctx.org.id)
        db.commit()
        return RedirectResponse(f"{target}?sarvam=connected")

    @r.get("/integrations/sarvam/agents/{provider_app_id}")
    def lookup_sarvam_agent(provider_app_id: str, request: Request,
                            ctx: OrgContext = Depends(org_access("agents.manage"))):
        from .sarvam_mcp import SarvamMCPError, fetch_agent
        app_id = check_app_id(provider_app_id)
        s = request.app.state.settings
        try:
            return fetch_agent(ctx.org, s.sarvam_mcp_encryption_key, s.sarvam_mcp_url, app_id)
        except SarvamMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    @r.get("/agents")
    def list_agents(status: str = "active", q: str = "", category: str = "", limit: int = 50, offset: int = 0,
                    ctx: OrgContext = Depends(org_access("agents.view")), db: Session = Depends(get_db)):
        limit, offset = clamp_page(limit, offset)
        cond = [Agent.organization_id == ctx.org.id]
        if status in ("active", "archived"):
            cond.append(Agent.status == status)
        elif status != "all":
            raise HTTPException(status_code=422, detail="Status must be active, archived or all.")
        if q.strip():
            like = f"%{q.strip().lower()[:100]}%"
            cond.append(or_(func.lower(Agent.name).like(like), func.lower(Agent.description).like(like)))
        if category.strip():
            cond.append(Agent.category == category.strip())
        total = db.scalar(select(func.count(Agent.id)).where(*cond)) or 0
        rows = db.scalars(select(Agent).where(*cond).order_by(func.lower(Agent.name)).limit(limit).offset(offset)).all()
        pub = {v.id: v for v in db.scalars(select(AgentVersion).where(
            AgentVersion.id.in_([a.published_version_id for a in rows if a.published_version_id])))}
        drafts = {v.agent_id for v in db.scalars(select(AgentVersion).where(
            AgentVersion.agent_id.in_([a.id for a in rows]), AgentVersion.status == "draft"))}
        items = []
        for a in rows:
            p = pub.get(a.published_version_id)
            items.append({**agent_out(a), "published_internal_version": p.internal_version if p else None,
                          "published_provider_app_version": p.provider_app_version if p else None,
                          "has_draft": a.id in drafts})
        return page(items, total, limit, offset)

    @r.post("/agents", status_code=201)
    def register_agent(body: AgentIn, request: Request, ctx: OrgContext = Depends(org_access("agents.manage")),
                       db: Session = Depends(get_db)):
        if body.provider not in PROVIDERS:
            raise HTTPException(status_code=422, detail="Only Sarvam agents are supported.")
        check_channels(body.channels)
        problems = schema_problems(body.variable_schema)
        if problems:
            unprocessable(problems)
        app_id = check_app_id(body.provider_app_id)
        a = Agent(organization_id=ctx.org.id, name=body.name.strip(), description=body.description,
                  category=body.category.strip(), provider=body.provider, provider_app_id=app_id,
                  channels=body.channels, status="active", created_by=ctx.user.id)
        db.add(a)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            # Same answer whichever organization holds it, so app ids of other tenants cannot be probed
            raise HTTPException(status_code=409, detail="That provider app is already registered.")
        v = AgentVersion(organization_id=ctx.org.id, agent_id=a.id, internal_version=1,
                         provider_app_version=body.provider_app_version, configuration_snapshot={},
                         variable_schema=body.variable_schema, status="draft", created_by=ctx.user.id)
        db.add(v)
        db.flush()
        audit(db, request, "agent.registered", actor=ctx.user, organization_id=ctx.org.id, target_type="agent",
              target_id=a.id, details={"name": a.name, "provider": a.provider, "provider_app_id": app_id})
        commit_or_conflict(db, "That provider app is already registered.")
        return agent_out(a, None, v)

    @r.get("/agents/{agent_id}")
    def get_agent(agent_id: str, ctx: OrgContext = Depends(org_access("agents.view")), db: Session = Depends(get_db)):
        a = agent_for(db, ctx, agent_id)
        pub = db.get(AgentVersion, a.published_version_id) if a.published_version_id else None
        counts = {"scenarios": db.scalar(select(func.count(TrainingScenario.id)).where(
                      TrainingScenario.agent_id == a.id, TrainingScenario.status != "archived")) or 0,
                  "open_assignments": db.scalar(select(func.count(AgentAssignment.id)).where(
                      AgentAssignment.agent_id == a.id, *_open(AgentAssignment, utcnow()))) or 0}
        return {**agent_out(a, pub, draft_of(db, a)), "counts": counts,
                "provider_app_id_locked": pub is not None}

    @r.patch("/agents/{agent_id}")
    def update_agent(agent_id: str, body: AgentPatch, request: Request,
                     ctx: OrgContext = Depends(org_access("agents.manage")), db: Session = Depends(get_db)):
        a = agent_for(db, ctx, agent_id)
        if a.status != "active":
            raise HTTPException(status_code=409, detail="Restore the agent before changing it.")
        changed = {}
        if body.name is not None:
            a.name = changed["name"] = body.name.strip()
        if body.description is not None:
            a.description = body.description
            changed["description"] = True
        if body.category is not None:
            a.category = changed["category"] = body.category.strip()
        if body.channels is not None:
            check_channels(body.channels)
            a.channels = changed["channels"] = body.channels
        if body.provider_app_id is not None:
            app_id = check_app_id(body.provider_app_id)
            if app_id != a.provider_app_id:
                if a.published_version_id is not None:
                    # Published versions point at this app; changing it would silently move old sessions
                    raise HTTPException(status_code=409, detail="The provider app id is fixed once a version is "
                                                                "published. Register a new agent for a different app.")
                a.provider_app_id = changed["provider_app_id"] = app_id
        audit(db, request, "agent.updated", actor=ctx.user, organization_id=ctx.org.id, target_type="agent",
              target_id=a.id, details=changed)
        commit_or_conflict(db, "That provider app is already registered.")
        return agent_out(a)

    @r.post("/agents/{agent_id}/archive")
    def archive_agent(agent_id: str, request: Request, ctx: OrgContext = Depends(org_access("agents.manage")),
                      db: Session = Depends(get_db)):
        a = agent_for(db, ctx, agent_id)
        if a.status != "archived":
            a.status, a.archived_at = "archived", utcnow()
            audit(db, request, "agent.archived", actor=ctx.user, organization_id=ctx.org.id, target_type="agent",
                  target_id=a.id)
            db.commit()
        return agent_out(a)

    @r.post("/agents/{agent_id}/restore")
    def restore_agent(agent_id: str, request: Request, ctx: OrgContext = Depends(org_access("agents.manage")),
                      db: Session = Depends(get_db)):
        a = agent_for(db, ctx, agent_id)
        if a.status != "active":
            a.status, a.archived_at = "active", None
            audit(db, request, "agent.restored", actor=ctx.user, organization_id=ctx.org.id, target_type="agent",
                  target_id=a.id)
            db.commit()
        return agent_out(a)

    # ---------- versions ----------
    @r.get("/agents/{agent_id}/versions")
    def list_versions(agent_id: str, ctx: OrgContext = Depends(org_access("agents.view")),
                      db: Session = Depends(get_db)):
        a = agent_for(db, ctx, agent_id)
        rows = db.scalars(select(AgentVersion).where(AgentVersion.agent_id == a.id)
                          .order_by(AgentVersion.internal_version.desc())).all()
        return [{**version_out(v), "is_current": v.id == a.published_version_id} for v in rows]

    @r.post("/agents/{agent_id}/versions", status_code=201)
    def new_draft(agent_id: str, body: NewDraftIn, request: Request,
                  ctx: OrgContext = Depends(org_access("agents.manage")), db: Session = Depends(get_db)):
        a = agent_for(db, ctx, agent_id)
        if a.status != "active":
            raise HTTPException(status_code=409, detail="Restore the agent before changing it.")
        if draft_of(db, a) is not None:
            raise HTTPException(status_code=409, detail="This agent already has a draft. Edit or discard it first.")
        base_id = body.based_on_version_id or a.published_version_id
        base = version_for(db, a, base_id) if base_id else None
        v = AgentVersion(organization_id=ctx.org.id, agent_id=a.id, internal_version=next_number(db, a),
                         provider_app_version=base.provider_app_version if base else None,
                         configuration_snapshot=dict(base.configuration_snapshot or {}) if base else {},
                         variable_schema=list(base.variable_schema or []) if base else [],
                         knowledge_base_reference=base.knowledge_base_reference if base else "",
                         rubric_reference=base.rubric_reference if base else "",
                         behavior_snapshot=dict(base.behavior_snapshot or {}) if base else {},
                         release_state="draft",
                         status="draft", based_on_version_id=base.id if base else None, created_by=ctx.user.id)
        db.add(v)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="This agent already has a draft. Edit or discard it first.")
        audit(db, request, "agent_version.draft_created", actor=ctx.user, organization_id=ctx.org.id,
              target_type="agent_version", target_id=v.id,
              details={"agent_id": a.id, "internal_version": v.internal_version, "based_on": v.based_on_version_id})
        commit_or_conflict(db, "This agent already has a draft. Edit or discard it first.")
        return version_out(v)

    @r.get("/agents/{agent_id}/versions/{version_id}")
    def get_version(agent_id: str, version_id: str, ctx: OrgContext = Depends(org_access("agents.view")),
                    db: Session = Depends(get_db)):
        a = agent_for(db, ctx, agent_id)
        v = version_for(db, a, version_id)
        return {**version_out(v), "is_current": v.id == a.published_version_id}

    def editable_draft(db: Session, a: Agent, version_id: str) -> AgentVersion:
        v = version_for(db, a, version_id)
        if v.status != "draft":
            raise HTTPException(status_code=409, detail="Published versions cannot be changed. Create a new draft.")
        if a.status != "active":
            raise HTTPException(status_code=409, detail="Restore the agent before changing it.")
        return v

    @r.patch("/agents/{agent_id}/versions/{version_id}")
    def update_draft(agent_id: str, version_id: str, body: VersionPatch, request: Request,
                     ctx: OrgContext = Depends(org_access("agents.manage")), db: Session = Depends(get_db)):
        a = agent_for(db, ctx, agent_id)
        v = editable_draft(db, a, version_id)
        data = body.model_dump(exclude_unset=True)
        # Guarded write first: it fails (and on Postgres locks the row) if the version was published meanwhile
        n = db.execute(update(AgentVersion).where(AgentVersion.id == v.id, AgentVersion.status == "draft")
                       .values(updated_at=utcnow())).rowcount
        if n != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="Published versions cannot be changed. Create a new draft.")
        if "configuration_snapshot" in data:
            problems = config_problems(data["configuration_snapshot"] if data["configuration_snapshot"] is not None else {})
            if problems:
                unprocessable(problems)
        if "variable_schema" in data:
            problems = schema_problems(data["variable_schema"] if data["variable_schema"] is not None else [])
            if problems:
                unprocessable(problems)
        for k, val in data.items():
            if val is None and k in ("configuration_snapshot",):
                val = {}
            elif val is None and k == "variable_schema":
                val = []
            elif val is None and k in ("knowledge_base_reference", "rubric_reference", "notes"):
                val = ""
            setattr(v, k, val)
        audit(db, request, "agent_version.draft_updated", actor=ctx.user, organization_id=ctx.org.id,
              target_type="agent_version", target_id=v.id, details={"fields": sorted(data)})
        db.commit()
        return version_out(v)

    @r.delete("/agents/{agent_id}/versions/{version_id}")
    def discard_draft(agent_id: str, version_id: str, request: Request,
                      ctx: OrgContext = Depends(org_access("agents.manage")), db: Session = Depends(get_db)):
        a = agent_for(db, ctx, agent_id)
        v = editable_draft(db, a, version_id)
        if db.scalar(select(func.count(TrainingScenario.id)).where(TrainingScenario.validated_version_id == v.id)):
            db.execute(update(TrainingScenario).where(TrainingScenario.validated_version_id == v.id)
                       .values(validated_version_id=None))
        n = db.execute(AgentVersion.__table__.delete().where(AgentVersion.id == v.id,
                                                             AgentVersion.status == "draft")).rowcount
        if n != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="Published versions cannot be deleted.")
        audit(db, request, "agent_version.draft_discarded", actor=ctx.user, organization_id=ctx.org.id,
              target_type="agent_version", target_id=version_id, details={"internal_version": v.internal_version})
        db.commit()
        return {"ok": True}

    @r.post("/agents/{agent_id}/versions/{version_id}/validate")
    def validate_version(agent_id: str, version_id: str, ctx: OrgContext = Depends(org_access("agents.manage")),
                         db: Session = Depends(get_db)):
        a = agent_for(db, ctx, agent_id)
        v = version_for(db, a, version_id)
        problems = publish_problems(a, v) if v.status == "draft" else []
        return {"ok": not problems, "problems": problems}

    @r.post("/agents/{agent_id}/versions/{version_id}/publish")
    def publish_version(agent_id: str, version_id: str, request: Request,
                        ctx: OrgContext = Depends(org_access("agents.manage")), db: Session = Depends(get_db)):
        a = agent_for(db, ctx, agent_id)
        v = editable_draft(db, a, version_id)
        problems = publish_problems(a, v)
        if problems:
            unprocessable(problems)
        now = utcnow()
        previous = a.published_version_id
        # One transaction: the version flips to published only if it is still a draft, and the agent's
        # current version moves with it. A second concurrent publish finds no draft and gets 409.
        n = db.execute(update(AgentVersion).where(AgentVersion.id == v.id, AgentVersion.status == "draft").values(
            status="published", published_at=now, published_by=ctx.user.id, updated_at=now)).rowcount
        if n != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="This version was already published.")
        db.execute(update(Agent).where(Agent.id == a.id).values(published_version_id=v.id, updated_at=now))
        audit(db, request, "agent_version.published", actor=ctx.user, organization_id=ctx.org.id,
              target_type="agent_version", target_id=v.id,
              details={"agent_id": a.id, "internal_version": v.internal_version, "provider_app_id": a.provider_app_id,
                       "provider_app_version": v.provider_app_version, "replaces": previous})
        db.commit()
        db.refresh(v)
        return version_out(v)

    # ---------- scenarios ----------
    def schema_version(db: Session, a: Agent) -> AgentVersion | None:
        """The version scenarios are checked against: the published one, else the draft."""
        if a.published_version_id:
            return db.get(AgentVersion, a.published_version_id)
        return draft_of(db, a)

    def check_scenario(db: Session, a: Agent, s: TrainingScenario):
        if s.difficulty not in DIFFICULTIES:
            raise HTTPException(status_code=422, detail=f"Difficulty must be one of {', '.join(DIFFICULTIES)}.")
        if s.status not in SCENARIO_STATUSES:
            raise HTTPException(status_code=422, detail="Status must be draft, active or archived.")
        if not _json_size_ok(s.agent_variables):
            raise HTTPException(status_code=422, detail="Agent variables are too large.")
        active = s.status == "active"
        if active and a.status != "active":
            raise HTTPException(status_code=409, detail="Scenarios of an archived agent cannot be active.")
        v = schema_version(db, a)
        if active and (v is None or v.status != "published"):
            raise HTTPException(status_code=409, detail="Publish a version of the agent before activating scenarios.")
        problems = variables_problems(v.variable_schema or [] if v else [], s.agent_variables or {}, require_all=active)
        if problems:
            unprocessable(problems)
        s.validated_version_id = v.id if v else None

    @r.get("/agents/{agent_id}/scenarios")
    def list_scenarios(agent_id: str, status: str = "", ctx: OrgContext = Depends(org_access("agents.view")),
                       db: Session = Depends(get_db)):
        a = agent_for(db, ctx, agent_id)
        q = select(TrainingScenario).where(TrainingScenario.agent_id == a.id,
                                           TrainingScenario.organization_id == ctx.org.id)
        if status:
            if status not in SCENARIO_STATUSES:
                raise HTTPException(status_code=422, detail="Status must be draft, active or archived.")
            q = q.where(TrainingScenario.status == status)
        return [scenario_out(s) for s in db.scalars(q.order_by(TrainingScenario.name))]

    @r.post("/agents/{agent_id}/scenarios", status_code=201)
    def create_scenario(agent_id: str, body: ScenarioIn, request: Request,
                        ctx: OrgContext = Depends(org_access("scenarios.manage")), db: Session = Depends(get_db)):
        a = agent_for(db, ctx, agent_id)
        if a.status != "active":
            raise HTTPException(status_code=409, detail="Restore the agent before adding scenarios.")
        s = TrainingScenario(organization_id=ctx.org.id, agent_id=a.id, created_by=ctx.user.id,
                             **{**body.model_dump(), "name": body.name.strip()})
        if s.status == "archived":
            raise HTTPException(status_code=422, detail="New scenarios start as draft or active.")
        check_scenario(db, a, s)
        db.add(s)
        db.flush()
        audit(db, request, "scenario.created", actor=ctx.user, organization_id=ctx.org.id, target_type="scenario",
              target_id=s.id, details={"agent_id": a.id, "name": s.name, "status": s.status})
        db.commit()
        return scenario_out(s)

    @r.get("/scenarios/{scenario_id}")
    def get_scenario(scenario_id: str, ctx: OrgContext = Depends(org_access("agents.view")),
                     db: Session = Depends(get_db)):
        return scenario_out(scoped_get(db, TrainingScenario, ctx.org.id, scenario_id))

    @r.patch("/scenarios/{scenario_id}")
    def update_scenario(scenario_id: str, body: ScenarioPatch, request: Request,
                        ctx: OrgContext = Depends(org_access("scenarios.manage")), db: Session = Depends(get_db)):
        s = scoped_get(db, TrainingScenario, ctx.org.id, scenario_id)
        a = scoped_get(db, Agent, ctx.org.id, s.agent_id)
        data = body.model_dump(exclude_unset=True)
        old_status = s.status
        for k, val in data.items():
            if val is None:
                continue
            setattr(s, k, val.strip() if k == "name" else val)
        if s.status == "archived":
            if old_status != "archived":
                s.archived_at = utcnow()
        else:
            s.archived_at = None
            check_scenario(db, a, s)
        audit(db, request, "scenario.updated", actor=ctx.user, organization_id=ctx.org.id, target_type="scenario",
              target_id=s.id, details={"fields": sorted(k for k, v in data.items() if v is not None),
                                       "status": s.status})
        db.commit()
        return scenario_out(s)

    # ---------- assignments ----------
    def target_roles(db: Session, org_id: str, user_ids: list[str]) -> dict[str, str]:
        return dict(db.execute(select(Membership.user_id, Membership.role).where(
            Membership.organization_id == org_id, Membership.status == "active", Membership.user_id.in_(user_ids))).all())

    def check_may_touch(ctx: OrgContext, db: Session, a: AgentAssignment):
        if a.user_id is None or RANK.get(ctx.role, 0) >= RANK[ADMIN]:
            return
        role = target_roles(db, ctx.org.id, [a.user_id]).get(a.user_id)
        if role is None or not can_assign_to(ctx.role, role):
            raise HTTPException(status_code=403, detail="Trainers can only manage assignments of trainees and teams.")

    def check_settings(db: Session, org_id: str, agent_ids: list[str], st: AssignmentSettings) -> dict:
        out = st.model_dump(exclude_none=True)
        ids = st.allowed_scenario_ids
        if ids is not None:
            ids = list(dict.fromkeys(ids))
            found = db.scalars(select(TrainingScenario).where(TrainingScenario.organization_id == org_id,
                                                              TrainingScenario.id.in_(ids))).all()
            if len(found) != len(ids):
                raise HTTPException(status_code=404, detail="One or more scenarios were not found.")
            if any(s.agent_id not in agent_ids for s in found):
                raise HTTPException(status_code=422, detail="Allowed scenarios must belong to the assigned agent.")
            if len(agent_ids) > 1:
                raise HTTPException(status_code=422, detail="Choose allowed scenarios one agent at a time.")
            out["allowed_scenario_ids"] = ids
        return out

    def check_window(starts: datetime | None, expires: datetime | None):
        if starts and expires and expires <= starts:
            raise HTTPException(status_code=422, detail="The end must be after the start.")

    @r.get("/assignments")
    def list_assignments(agent_id: str = "", user_id: str = "", team_id: str = "", state: str = "open",
                         limit: int = 50, offset: int = 0, ctx: OrgContext = Depends(org_access("assignments.manage")),
                         db: Session = Depends(get_db)):
        limit, offset = clamp_page(limit, offset)
        now = utcnow()
        cond = [AgentAssignment.organization_id == ctx.org.id]
        if agent_id:
            cond.append(AgentAssignment.agent_id == agent_id)
        if user_id:
            cond.append(AgentAssignment.user_id == user_id)
        if team_id:
            cond.append(AgentAssignment.team_id == team_id)
        if state == "open":
            cond += [AgentAssignment.revoked_at.is_(None),
                     or_(AgentAssignment.expires_at.is_(None), AgentAssignment.expires_at > now)]
        elif state == "active":
            cond += list(_open(AgentAssignment, now))
        elif state == "revoked":
            cond.append(AgentAssignment.revoked_at.is_not(None))
        elif state == "expired":
            cond += [AgentAssignment.revoked_at.is_(None), AgentAssignment.expires_at <= now]
        elif state != "all":
            raise HTTPException(status_code=422, detail="State must be open, active, revoked, expired or all.")
        total = db.scalar(select(func.count(AgentAssignment.id)).where(*cond)) or 0
        rows = db.scalars(select(AgentAssignment).where(*cond).order_by(AgentAssignment.created_at.desc())
                          .limit(limit).offset(offset)).all()
        return page([assignment_out(a, now, _names(db, ctx.org.id, rows)) for a in rows], total, limit, offset)

    def _names(db: Session, org_id: str, rows: list[AgentAssignment]) -> dict:
        names = {}
        for a in db.scalars(select(Agent).where(Agent.organization_id == org_id,
                                                Agent.id.in_({x.agent_id for x in rows}))):
            names[("agent", a.id)] = a.name
        for u in db.scalars(select(User).where(User.id.in_({x.user_id for x in rows if x.user_id}))):
            names[("user", u.id)] = u.email
        for t in db.scalars(select(Team).where(Team.organization_id == org_id,
                                               Team.id.in_({x.team_id for x in rows if x.team_id}))):
            names[("team", t.id)] = t.name
        return names

    @r.post("/assignments", status_code=201)
    def create_assignments(body: AssignIn, request: Request,
                           ctx: OrgContext = Depends(org_access("assignments.manage")), db: Session = Depends(get_db)):
        """Assigns each agent to each user and team. All or nothing: any id outside this organization,
        or any person the caller may not assign to, fails the whole request."""
        agent_ids = list(dict.fromkeys(body.agent_ids))
        user_ids = list(dict.fromkeys(body.user_ids))
        team_ids = list(dict.fromkeys(body.team_ids))
        if not user_ids and not team_ids:
            raise HTTPException(status_code=422, detail="Choose at least one person or team.")
        if len(agent_ids) * (len(user_ids) + len(team_ids)) > 1000:
            raise HTTPException(status_code=422, detail="At most 1000 assignments at a time.")
        agents = db.scalars(select(Agent).where(Agent.organization_id == ctx.org.id, Agent.id.in_(agent_ids))).all()
        if len(agents) != len(agent_ids):
            raise HTTPException(status_code=404, detail="One or more agents were not found.")
        if any(a.status != "active" for a in agents):
            raise HTTPException(status_code=409, detail="Archived agents cannot be assigned.")
        # An assignment is usable only through the agent's current immutable published version (the
        # same invariant enforced by entitlements()).  Rejecting drafts here prevents admins from
        # creating apparently-active assignments that the trainee dashboard must correctly hide.
        published = {v.id: v for v in db.scalars(select(AgentVersion).where(
            AgentVersion.id.in_([a.published_version_id for a in agents if a.published_version_id])))}
        if any(not a.published_version_id
               or (v := published.get(a.published_version_id)) is None
               or v.status != "published" or v.organization_id != ctx.org.id or v.agent_id != a.id
               for a in agents):
            raise HTTPException(status_code=409,
                                detail="Publish every selected agent before assigning it to people or teams.")
        roles = target_roles(db, ctx.org.id, user_ids) if user_ids else {}
        if len(roles) != len(user_ids):
            raise HTTPException(status_code=404, detail="One or more people are not members of this organization.")
        refused = [u for u, role in roles.items() if not can_assign_to(ctx.role, role)]
        if refused:
            raise HTTPException(status_code=403, detail="Trainers can only assign agents to trainees.")
        if team_ids:
            teams = db.scalars(select(Team).where(Team.organization_id == ctx.org.id, Team.id.in_(team_ids))).all()
            if len(teams) != len(team_ids):
                raise HTTPException(status_code=404, detail="One or more teams were not found.")
            if any(t.status != "active" for t in teams):
                raise HTTPException(status_code=409, detail="Archived teams cannot be given agents.")
        now = utcnow()
        starts, expires = to_utc(body.starts_at) or now, to_utc(body.expires_at)
        check_window(starts, expires)
        if expires is not None and expires <= now:
            raise HTTPException(status_code=422, detail="The end date is already in the past.")
        settings = check_settings(db, ctx.org.id, agent_ids, body.settings)
        created, skipped = [], []
        targets = [("user", u) for u in user_ids] + [("team", t) for t in team_ids]
        for agent_id in agent_ids:
            for kind, tid in targets:
                col = AgentAssignment.user_id if kind == "user" else AgentAssignment.team_id
                existing = db.scalars(select(AgentAssignment).where(
                    AgentAssignment.agent_id == agent_id, col == tid, AgentAssignment.revoked_at.is_(None))).first()
                if existing is not None:
                    if existing.expires_at is not None and existing.expires_at <= now:
                        existing.revoked_at, existing.revoke_reason, existing.revoked_by = now, "replaced", ctx.user.id
                        db.flush()
                    else:
                        skipped.append({"agent_id": agent_id, f"{kind}_id": tid, "assignment_id": existing.id})
                        continue
                a = AgentAssignment(organization_id=ctx.org.id, agent_id=agent_id, assigned_by=ctx.user.id,
                                    starts_at=starts, expires_at=expires, settings=settings,
                                    **{f"{kind}_id": tid})
                db.add(a)
                db.flush()
                created.append(a)
                audit(db, request, "assignment.created", actor=ctx.user, organization_id=ctx.org.id,
                      target_type="assignment", target_id=a.id,
                      details={"agent_id": agent_id, f"{kind}_id": tid, "expires_at": iso(expires)})
        commit_or_conflict(db, "Some of these were assigned at the same time. Refresh and try again.")
        return {"created": [assignment_out(a, now) for a in created], "skipped": skipped}

    @r.get("/assignments/{assignment_id}")
    def get_assignment(assignment_id: str, ctx: OrgContext = Depends(org_access("assignments.manage")),
                       db: Session = Depends(get_db)):
        a = scoped_get(db, AgentAssignment, ctx.org.id, assignment_id)
        history = db.scalars(select(AgentAssignment).where(
            AgentAssignment.organization_id == ctx.org.id, AgentAssignment.agent_id == a.agent_id,
            AgentAssignment.user_id == a.user_id if a.user_id else AgentAssignment.team_id == a.team_id)
            .order_by(AgentAssignment.created_at.desc()).limit(50)).all()
        now = utcnow()
        names = _names(db, ctx.org.id, [a, *history])
        return {**assignment_out(a, now, names), "history": [assignment_out(h, now, names) for h in history]}

    @r.patch("/assignments/{assignment_id}")
    def update_assignment(assignment_id: str, body: AssignmentPatch, request: Request,
                          ctx: OrgContext = Depends(org_access("assignments.manage")), db: Session = Depends(get_db)):
        a = scoped_get(db, AgentAssignment, ctx.org.id, assignment_id)
        check_may_touch(ctx, db, a)
        if a.revoked_at is not None:
            raise HTTPException(status_code=409, detail="Revoked assignments cannot be changed. Assign again instead.")
        starts = to_utc(body.starts_at) if body.starts_at else a.starts_at
        expires = None if body.clear_expiry else (to_utc(body.expires_at) if body.expires_at else a.expires_at)
        check_window(starts, expires)
        a.starts_at, a.expires_at = starts, expires
        if body.settings is not None:
            a.settings = check_settings(db, ctx.org.id, [a.agent_id], body.settings)
        audit(db, request, "assignment.updated", actor=ctx.user, organization_id=ctx.org.id, target_type="assignment",
              target_id=a.id, details={"starts_at": iso(starts), "expires_at": iso(expires),
                                       "settings": body.settings is not None})
        db.commit()
        return assignment_out(a, utcnow())

    @r.post("/assignments/{assignment_id}/revoke")
    def revoke_assignment(assignment_id: str, request: Request,
                          ctx: OrgContext = Depends(org_access("assignments.manage")), db: Session = Depends(get_db)):
        a = scoped_get(db, AgentAssignment, ctx.org.id, assignment_id)
        check_may_touch(ctx, db, a)
        if a.revoked_at is None:
            a.revoked_at, a.revoked_by, a.revoke_reason = utcnow(), ctx.user.id, "revoked"
            audit(db, request, "assignment.revoked", actor=ctx.user, organization_id=ctx.org.id,
                  target_type="assignment", target_id=a.id,
                  details={"agent_id": a.agent_id, "user_id": a.user_id, "team_id": a.team_id})
            db.commit()
        return assignment_out(a, utcnow())

    # ---------- my training (any member) ----------
    def my_agent_out(db: Session, ent: Entitlement, with_scenarios: bool) -> dict:
        a, v = ent.agent, ent.version
        out = {"id": a.id, "name": a.name, "description": a.description, "category": a.category,
               "channels": a.channels or [], "version": {"id": v.id, "internal_version": v.internal_version,
                                                          "published_at": iso(v.published_at),
                                                          "variable_schema": v.variable_schema or []},
               "access": {"source": ent.source, "expires_at": iso(ent.expires_at),
                          "max_sessions": ent.max_sessions, "max_minutes_per_session": ent.max_minutes_per_session},
               # Phase 2 stores the channels; starting a session arrives in a later phase
               "training_available": False}
        scen = allowed_scenarios(db, ent)
        out["scenario_count"] = len(scen)
        if with_scenarios:
            out["scenarios"] = [{"id": s.id, "name": s.name, "description": s.description,
                                 "difficulty": s.difficulty, "objective": s.objective} for s in scen]
        return out

    @r.get("/my/agents")
    def my_agents(ctx: OrgContext = Depends(org_access("training.self")), db: Session = Depends(get_db)):
        return [my_agent_out(db, e, with_scenarios=False) for e in entitlements(db, ctx.org.id, ctx.user.id)]

    @r.get("/my/agents/{agent_id}")
    def my_agent(agent_id: str, ctx: OrgContext = Depends(org_access("training.self")), db: Session = Depends(get_db)):
        ents = entitlements(db, ctx.org.id, ctx.user.id, agent_id)
        if not ents:
            raise HTTPException(status_code=404, detail="Not found.")
        return my_agent_out(db, ents[0], with_scenarios=True)

    def my_training_profile(db: Session, ctx: OrgContext, agent_id: str, create: bool = False):
        # The entitlement is deliberately checked on every operation. A saved profile does not preserve
        # access after an assignment is revoked or expires.
        if not entitlements(db, ctx.org.id, ctx.user.id, agent_id):
            raise HTTPException(status_code=404, detail="Not found.")
        row = db.scalars(select(TraineeAgentTrainingProfile).where(
            TraineeAgentTrainingProfile.organization_id == ctx.org.id,
            TraineeAgentTrainingProfile.user_id == ctx.user.id,
            TraineeAgentTrainingProfile.agent_id == agent_id)).first()
        if row is None and create:
            row = TraineeAgentTrainingProfile(organization_id=ctx.org.id, user_id=ctx.user.id,
                                               agent_id=agent_id, instructions="", variable_values={}, sources=[])
            db.add(row); db.flush()
        return row

    def profile_out(row):
        return {"instructions": row.instructions if row else "",
                "variable_values": dict(row.variable_values or {}) if row else {},
                "sources": list(row.sources or []) if row else [],
                "updated_at": iso(row.updated_at) if row else None}

    def add_profile_source(row, source: dict):
        sources = list(row.sources or [])
        sources.append(source)
        if sum(len(str(x.get("text") or "")) for x in sources) > 60_000:
            raise HTTPException(status_code=422, detail="Your personal agent training can contain at most 60,000 characters.")
        row.sources = sources
        row.updated_at = utcnow()

    @r.get("/my/agents/{agent_id}/training-profile")
    def get_my_training_profile(agent_id: str, ctx: OrgContext = Depends(org_access("training.self")),
                                db: Session = Depends(get_db)):
        return profile_out(my_training_profile(db, ctx, agent_id))

    @r.put("/my/agents/{agent_id}/training-profile")
    def update_my_training_profile(agent_id: str, body: MyTrainingProfileIn, request: Request,
                                   ctx: OrgContext = Depends(org_access("training.self")), db: Session = Depends(get_db)):
        row = my_training_profile(db, ctx, agent_id, create=True)
        ent = entitlements(db, ctx.org.id, ctx.user.id, agent_id)[0]
        reserved = {"agent_name", "user_name", "trainee_name", "trainee_training_context", "user_training_context"}
        if reserved & set(body.variable_values):
            raise HTTPException(status_code=422, detail="Identity and training-context variables are filled by DIDM.")
        problems = variables_problems(ent.version.variable_schema or [], body.variable_values, require_all=False)
        if problems:
            raise HTTPException(status_code=422, detail=" ".join(problems))
        row.instructions, row.variable_values, row.updated_at = (body.instructions.strip(),
                                                                 dict(body.variable_values), utcnow())
        audit(db, request, "trainee.agent_training_updated", actor=ctx.user, organization_id=ctx.org.id,
              target_type="agent", target_id=agent_id, details={"source_count": len(row.sources or [])})
        db.commit()
        return profile_out(row)

    @r.post("/my/agents/{agent_id}/training-profile/text", status_code=201)
    def add_my_training_text(agent_id: str, body: MyTrainingTextIn, request: Request,
                             ctx: OrgContext = Depends(org_access("training.self")), db: Session = Depends(get_db)):
        row = my_training_profile(db, ctx, agent_id, create=True)
        text_value = body.text.strip()
        add_profile_source(row, {"id": hashlib.sha256((body.title + text_value + str(utcnow())).encode()).hexdigest()[:24],
                                 "kind": "text", "title": body.title.strip(), "text": text_value,
                                 "created_at": iso(utcnow())})
        audit(db, request, "trainee.agent_training_source_added", actor=ctx.user, organization_id=ctx.org.id,
              target_type="agent", target_id=agent_id, details={"kind": "text"})
        db.commit()
        return profile_out(row)

    @r.post("/my/agents/{agent_id}/training-profile/pdf", status_code=201)
    def add_my_training_pdf(agent_id: str, body: MyTrainingPdfIn, request: Request,
                            ctx: OrgContext = Depends(org_access("training.self")), db: Session = Depends(get_db)):
        row = my_training_profile(db, ctx, agent_id, create=True)
        try:
            raw = base64.b64decode(body.content_base64, validate=True)
        except Exception:
            raise HTTPException(status_code=422, detail="The PDF upload is not valid base64.")
        if len(raw) > 5_000_000 or not raw.startswith(b"%PDF-"):
            raise HTTPException(status_code=422, detail="Upload a valid PDF no larger than 5 MB.")
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted:
                raise ValueError("encrypted")
            extracted = "\n\n".join((p.extract_text() or "").strip() for p in reader.pages).strip()
        except Exception:
            raise HTTPException(status_code=422, detail="This PDF could not be safely read. Encrypted or malformed PDFs are not accepted.")
        if not extracted:
            raise HTTPException(status_code=422, detail="No selectable text was found in this PDF. Scanned PDFs need OCR first.")
        extracted = extracted[:30_000]
        add_profile_source(row, {"id": hashlib.sha256(raw).hexdigest()[:24], "kind": "pdf",
                                 "title": body.filename.strip(), "text": extracted,
                                 "sha256": hashlib.sha256(raw).hexdigest(), "created_at": iso(utcnow())})
        audit(db, request, "trainee.agent_training_source_added", actor=ctx.user, organization_id=ctx.org.id,
              target_type="agent", target_id=agent_id, details={"kind": "pdf", "size_bytes": len(raw)})
        db.commit()
        return profile_out(row)

    @r.post("/my/agents/{agent_id}/training-profile/transcript", status_code=201)
    def add_my_training_transcript(agent_id: str, body: MyTrainingTranscriptIn, request: Request,
                                   ctx: OrgContext = Depends(org_access("training.self")), db: Session = Depends(get_db)):
        row = my_training_profile(db, ctx, agent_id, create=True)
        session = db.scalars(select(TrainingSession).where(
            TrainingSession.id == body.session_id, TrainingSession.organization_id == ctx.org.id,
            TrainingSession.user_id == ctx.user.id, TrainingSession.agent_id == agent_id)).first()
        if session is None:
            raise HTTPException(status_code=404, detail="That is not one of your calls with this agent.")
        transcript = db.scalars(select(TrainingTranscript).where(
            TrainingTranscript.session_id == session.id, TrainingTranscript.purged_at.is_(None))).first()
        if transcript is None or transcript.status not in ("complete", "partial"):
            raise HTTPException(status_code=409, detail="This call transcript is not available.")
        turns = db.scalars(select(TrainingTranscriptTurn).where(
            TrainingTranscriptTurn.transcript_id == transcript.id).order_by(TrainingTranscriptTurn.sequence_number)).all()
        value = "\n".join(f"{x.speaker}: {x.text}" for x in turns).strip()[:30_000]
        if not value:
            raise HTTPException(status_code=409, detail="This call transcript is empty.")
        add_profile_source(row, {"id": hashlib.sha256((session.id + value).encode()).hexdigest()[:24],
                                 "kind": "transcript", "title": f"Practice call {session.created_at.date().isoformat()}",
                                 "text": value, "session_id": session.id, "created_at": iso(utcnow())})
        audit(db, request, "trainee.agent_training_source_added", actor=ctx.user, organization_id=ctx.org.id,
              target_type="agent", target_id=agent_id, details={"kind": "transcript", "session_id": session.id})
        db.commit()
        return profile_out(row)

    @r.delete("/my/agents/{agent_id}/training-profile/sources/{source_id}")
    def delete_my_training_source(agent_id: str, source_id: str, request: Request,
                                  ctx: OrgContext = Depends(org_access("training.self")), db: Session = Depends(get_db)):
        row = my_training_profile(db, ctx, agent_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Not found.")
        kept = [x for x in (row.sources or []) if x.get("id") != source_id]
        if len(kept) == len(row.sources or []):
            raise HTTPException(status_code=404, detail="Not found.")
        row.sources, row.updated_at = kept, utcnow()
        audit(db, request, "trainee.agent_training_source_removed", actor=ctx.user, organization_id=ctx.org.id,
              target_type="agent", target_id=agent_id, details={"source_id": source_id})
        db.commit()
        return profile_out(row)

    @r.get("/my/assignments")
    def my_assignments(ctx: OrgContext = Depends(org_access("training.self")), db: Session = Depends(get_db)):
        now = utcnow()
        teams = active_team_ids(db, ctx.org.id, ctx.user.id)
        target = AgentAssignment.user_id == ctx.user.id
        if teams:
            target = or_(target, AgentAssignment.team_id.in_(teams))
        rows = db.scalars(select(AgentAssignment).join(Agent, Agent.id == AgentAssignment.agent_id).where(
            AgentAssignment.organization_id == ctx.org.id, target, AgentAssignment.revoked_at.is_(None),
            or_(AgentAssignment.expires_at.is_(None), AgentAssignment.expires_at > now), Agent.status == "active")
            .order_by(AgentAssignment.starts_at)).all()
        names = _names(db, ctx.org.id, rows)
        keep = ("id", "agent_id", "agent_name", "team_id", "team_name", "starts_at", "expires_at", "state", "settings")
        return [{k: v for k, v in assignment_out(a, now, names).items() if k in keep} for a in rows]

    return r
