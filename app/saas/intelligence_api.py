"""HTTP API for training intelligence: rubrics, scorecards (transcript, evaluation, recording), progress and
analytics, recording and evaluation settings, and phone verification codes.

Aggregation rules (also in docs/ARCHITECTURE.md):
- A practice session is one where the trainee talked to the agent: connected here, or connected according
  to the provider after reconciliation.
- Scores come only from evaluations with status completed, one per session (its latest). Sessions that
  were not evaluated, or had insufficient evidence, never enter an average.
- Practice minutes use the provider-reported duration when known, otherwise our own.
"""
import hashlib
import hmac
import secrets
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import utcnow
from .agents import iso
from .analytics import SESSION_HEADER, TRAINEE_HEADER, OrgAnalytics, csv_lines
from .auth import OrgContext, audit, get_db, org_access, scoped_get
from .intelligence import (DEFAULT_CRITERIA, EVALUATOR_VERSION, enqueue, latest_published, rubric_problems,
                           transcript_turns)
from .models import (Agent, EvaluationJob, EvaluationRubric, EvaluationRubricVersion, Membership,
                     PhoneVerificationChallenge, RetentionRun, Team, TrainingEvaluation, TrainingOrgLimits,
                     TrainingOrgSettings, TrainingRecording, TrainingScenario, TrainingSession, TrainingTranscript,
                     TrainingUsageAdjustment, User)
from .permissions import has_permission

OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5


# ---------- shapes ----------
def version_out(v: EvaluationRubricVersion) -> dict:
    return {"id": v.id, "rubric_id": v.rubric_id, "version": v.version, "status": v.status, "criteria": v.criteria,
            "weights": v.weights, "scale_max": v.scale_max, "scoring_instructions": v.scoring_instructions,
            "min_trainee_turns": v.min_trainee_turns, "published_at": iso(v.published_at),
            "created_at": iso(v.created_at), "updated_at": iso(v.updated_at)}


def rubric_out(r: EvaluationRubric, versions: list | None = None) -> dict:
    out = {"id": r.id, "name": r.name, "description": r.description, "status": r.status,
           "created_at": iso(r.created_at), "updated_at": iso(r.updated_at)}
    if versions is not None:
        out["versions"] = [version_out(v) for v in versions]
        pub = [v for v in versions if v.status == "published"]
        out["published_version"] = max((v.version for v in pub), default=None)
        out["has_draft"] = any(v.status == "draft" for v in versions)
    return out


def evaluation_out(e: TrainingEvaluation, version: EvaluationRubricVersion | None, rubric_name: str | None) -> dict:
    names = {c["key"]: c["name"] for c in (version.criteria if version else [])}
    weights = {c["key"]: c["weight"] for c in (version.criteria if version else [])}
    return {"id": e.id, "status": e.status, "overall_score": e.overall_score, "confidence": e.confidence,
            "rubric": {"id": version.rubric_id if version else None, "name": rubric_name,
                       "version_id": e.rubric_version_id, "version": version.version if version else None,
                       "scale_max": version.scale_max if version else None},
            "evaluator": {"provider": e.evaluator_provider, "model": e.evaluator_model, "version": e.evaluator_version},
            "criteria": [{**c, "name": names.get(c["key"], c["key"]), "weight": weights.get(c["key"])}
                         for c in (e.criterion_results or [])],
            "feedback": e.feedback or {}, "error_code": e.error_code, "evaluated_at": iso(e.evaluated_at)}


def consent_version(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()[:16]


# ---------- inputs ----------
class CriterionIn(BaseModel):
    key: str = Field(max_length=40)
    name: str = Field(max_length=120)
    description: str = Field(default="", max_length=1000)
    weight: int


class RubricIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    criteria: list[CriterionIn] | None = None  # None = start from the default template
    scale_max: int = 5
    scoring_instructions: str = Field(default="", max_length=4000)
    min_trainee_turns: int = 3


class RubricPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, max_length=20)


class VersionPatch(BaseModel):
    criteria: list[CriterionIn] | None = None
    scale_max: int | None = None
    scoring_instructions: str | None = Field(default=None, max_length=4000)
    min_trainee_turns: int | None = None


class ScenarioRubricIn(BaseModel):
    rubric_id: str | None = Field(default=None, max_length=36)


class SettingsIn(BaseModel):
    recording_enabled: bool | None = None
    recording_retention_days: int | None = Field(default=None, ge=1, le=365)
    storage_provider: str | None = Field(default=None, max_length=20)
    consent_text: str | None = Field(default=None, max_length=4000)
    default_rubric_id: str | None = Field(default=None, max_length=36)
    clear_default_rubric: bool = False
    # Phase 5: the notice before every practice call (empty text removes it), transcript retention and legal hold
    practice_notice_text: str | None = Field(default=None, max_length=4000)
    transcript_retention_days: int | None = Field(default=None, ge=7, le=3650)
    keep_transcripts: bool = False  # true removes the transcript retention period (keep indefinitely)
    legal_hold: bool | None = None
    legal_hold_reason: str | None = Field(default=None, max_length=500)


class EvaluateIn(BaseModel):
    rubric_version_id: str | None = Field(default=None, max_length=36)


class OtpVerifyIn(BaseModel):
    code: str = Field(min_length=4, max_length=10)


# ---------- aggregation ----------
def practised(s: TrainingSession) -> bool:
    return s.connected_at is not None or (s.provider_status == "connected" and (s.provider_duration_seconds or 0) > 0)


def practice_seconds(s: TrainingSession) -> int:
    if not practised(s):
        return 0
    return int(s.provider_duration_seconds if s.provider_duration_seconds is not None else (s.duration_seconds or 0))


def latest_scores(db: Session, org_id: str, session_ids) -> dict:
    """session_id -> its latest completed evaluation."""
    out = {}
    ids = list(session_ids)
    for i in range(0, len(ids), 500):
        for e in db.scalars(select(TrainingEvaluation).where(
                TrainingEvaluation.organization_id == org_id, TrainingEvaluation.session_id.in_(ids[i:i + 500]),
                TrainingEvaluation.status == "completed").order_by(TrainingEvaluation.evaluated_at)):
            out[e.session_id] = e  # later rows win
    return out


def criterion_names(db: Session, evals) -> dict:
    vids = {e.rubric_version_id for e in evals}
    names = {}
    if vids:
        for v in db.scalars(select(EvaluationRubricVersion).where(EvaluationRubricVersion.id.in_(vids))):
            for c in v.criteria:
                names.setdefault(c["key"], c["name"])
    return names


def skill_table(db: Session, evals) -> list[dict]:
    """Mean criterion score (0-100) per criterion key, with how many evaluations scored it."""
    scale = {}
    vids = {e.rubric_version_id for e in evals}
    if vids:
        scale = {v.id: v.scale_max for v in db.scalars(select(EvaluationRubricVersion).where(
            EvaluationRubricVersion.id.in_(vids)))}
    acc = defaultdict(list)
    for e in evals:
        for c in e.criterion_results or []:
            if c.get("score") is not None and scale.get(e.rubric_version_id):
                acc[c["key"]].append(100 * c["score"] / scale[e.rubric_version_id])
    names = criterion_names(db, evals)
    return sorted(({"key": k, "name": names.get(k, k), "average": round(sum(v) / len(v)), "samples": len(v)}
                   for k, v in acc.items()), key=lambda r: -r["average"])


def avg(xs):
    xs = list(xs)
    return round(sum(xs) / len(xs)) if xs else None


def progress_for(db: Session, org_id: str, user_id: str) -> dict:
    sessions = db.scalars(select(TrainingSession).where(TrainingSession.organization_id == org_id,
                                                        TrainingSession.user_id == user_id)
                          .order_by(TrainingSession.created_at)).all()
    done = [s for s in sessions if practised(s)]
    scores = latest_scores(db, org_id, [s.id for s in done])
    evals = [scores[s.id] for s in done if s.id in scores]
    skills = skill_table(db, evals)
    ranked = [k for k in skills if k["samples"] >= 2]
    recent = sorted(evals, key=lambda e: e.evaluated_at, reverse=True)[:3]
    return {
        "practice_sessions": len(done), "evaluated_sessions": len(evals),
        "not_evaluated_sessions": len(done) - len(evals),
        "average_score": avg(e.overall_score for e in evals),
        "practice_minutes": round(sum(practice_seconds(s) for s in done) / 60, 1),
        "trend": [{"session_id": e.session_id, "date": iso(e.evaluated_at), "score": e.overall_score}
                  for e in sorted(evals, key=lambda e: e.evaluated_at)][-20:],
        "skills": skills,
        "strongest": ranked[:2], "needs_work": [k for k in reversed(ranked) if k not in ranked[:2]][:2],
        "recent_feedback": [{"session_id": e.session_id, "date": iso(e.evaluated_at), "score": e.overall_score,
                             "summary": (e.feedback or {}).get("summary"),
                             "improvements": (e.feedback or {}).get("improvements", [])[:3]} for e in recent],
        "rules": "Scores average only sessions with a completed evaluation; skills need at least two scored sessions.",
    }


def build_intelligence_router(training, intelligence, recordings) -> APIRouter:
    r = APIRouter(prefix="/api/v1/organizations/{org_id}")

    def owner_or(db: Session, ctx: OrgContext, session_id: str, permission: str) -> TrainingSession:
        sess = scoped_get(db, TrainingSession, ctx.org.id, session_id)
        if sess.user_id != ctx.user.id and not has_permission(ctx.role, permission):
            raise HTTPException(status_code=404, detail="Not found.")
        return sess

    # ---------- rubrics ----------
    @r.get("/rubrics")
    def list_rubrics(ctx: OrgContext = Depends(org_access("training.view")), db: Session = Depends(get_db)):
        rows = db.scalars(select(EvaluationRubric).where(EvaluationRubric.organization_id == ctx.org.id)
                          .order_by(EvaluationRubric.name)).all()
        vs = defaultdict(list)
        for v in db.scalars(select(EvaluationRubricVersion).where(EvaluationRubricVersion.organization_id == ctx.org.id)
                            .order_by(EvaluationRubricVersion.version)):
            vs[v.rubric_id].append(v)
        return [{k: v for k, v in rubric_out(x, vs[x.id]).items() if k != "versions"} for x in rows]

    @r.get("/rubric-template")
    def rubric_template(ctx: OrgContext = Depends(org_access("training.view"))):
        return {"criteria": DEFAULT_CRITERIA, "scale_max": 5, "min_trainee_turns": 3}

    def check_version(criteria, scale_max, min_turns, instructions):
        problems = rubric_problems(criteria, scale_max, min_turns, instructions)
        if problems:
            raise HTTPException(status_code=422, detail=" ".join(problems))

    @r.post("/rubrics", status_code=201)
    def create_rubric(body: RubricIn, request: Request, ctx: OrgContext = Depends(org_access("rubrics.manage")),
                      db: Session = Depends(get_db)):
        criteria = [c.model_dump() for c in body.criteria] if body.criteria is not None else [dict(c) for c in DEFAULT_CRITERIA]
        check_version(criteria, body.scale_max, body.min_trainee_turns, body.scoring_instructions)
        if db.scalars(select(EvaluationRubric).where(EvaluationRubric.organization_id == ctx.org.id,
                                                     EvaluationRubric.name == body.name.strip())).first():
            raise HTTPException(status_code=409, detail="A rubric with this name already exists.")
        now = utcnow()
        rub = EvaluationRubric(organization_id=ctx.org.id, name=body.name.strip(), description=body.description,
                               status="active", created_by=ctx.user.id, created_at=now, updated_at=now)
        db.add(rub)
        db.flush()
        v = EvaluationRubricVersion(organization_id=ctx.org.id, rubric_id=rub.id, version=1, status="draft",
                                    criteria=criteria, weights={}, scale_max=body.scale_max,
                                    scoring_instructions=body.scoring_instructions,
                                    min_trainee_turns=body.min_trainee_turns, created_by=ctx.user.id,
                                    created_at=now, updated_at=now)
        db.add(v)
        audit(db, request, "rubric.created", actor=ctx.user, organization_id=ctx.org.id, target_type="rubric",
              target_id=rub.id)
        db.commit()
        return rubric_out(rub, [v])

    def load_rubric(db, ctx, rubric_id):
        rub = scoped_get(db, EvaluationRubric, ctx.org.id, rubric_id)
        versions = db.scalars(select(EvaluationRubricVersion).where(EvaluationRubricVersion.rubric_id == rub.id)
                              .order_by(EvaluationRubricVersion.version)).all()
        return rub, versions

    @r.get("/rubrics/{rubric_id}")
    def get_rubric(rubric_id: str, ctx: OrgContext = Depends(org_access("training.view")), db: Session = Depends(get_db)):
        rub, versions = load_rubric(db, ctx, rubric_id)
        return rubric_out(rub, versions)

    @r.patch("/rubrics/{rubric_id}")
    def patch_rubric(rubric_id: str, body: RubricPatch, request: Request,
                     ctx: OrgContext = Depends(org_access("rubrics.manage")), db: Session = Depends(get_db)):
        rub = scoped_get(db, EvaluationRubric, ctx.org.id, rubric_id)
        if body.status is not None and body.status not in ("active", "archived"):
            raise HTTPException(status_code=422, detail="Status must be active or archived.")
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(rub, k, v.strip() if k == "name" else v)
        rub.updated_at = utcnow()
        audit(db, request, "rubric.updated", actor=ctx.user, organization_id=ctx.org.id, target_type="rubric",
              target_id=rub.id, details=body.model_dump(exclude_none=True, exclude={"description"}))
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise HTTPException(status_code=409, detail="A rubric with this name already exists.")
        return rubric_out(*load_rubric(db, ctx, rubric_id))

    @r.post("/rubrics/{rubric_id}/versions", status_code=201)
    def new_draft(rubric_id: str, request: Request, ctx: OrgContext = Depends(org_access("rubrics.manage")),
                  db: Session = Depends(get_db)):
        rub, versions = load_rubric(db, ctx, rubric_id)
        if any(v.status == "draft" for v in versions):
            raise HTTPException(status_code=409, detail="This rubric already has a draft.")
        base = latest_published(db, rub.id)
        now = utcnow()
        v = EvaluationRubricVersion(
            organization_id=ctx.org.id, rubric_id=rub.id, version=max((x.version for x in versions), default=0) + 1,
            status="draft", criteria=[dict(c) for c in (base.criteria if base else DEFAULT_CRITERIA)], weights={},
            scale_max=base.scale_max if base else 5, scoring_instructions=base.scoring_instructions if base else "",
            min_trainee_turns=base.min_trainee_turns if base else 3, created_by=ctx.user.id, created_at=now,
            updated_at=now)
        db.add(v)
        audit(db, request, "rubric.draft_created", actor=ctx.user, organization_id=ctx.org.id,
              target_type="rubric", target_id=rub.id)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise HTTPException(status_code=409, detail="This rubric already has a draft.")
        return version_out(v)

    def draft(db, ctx, version_id) -> EvaluationRubricVersion:
        v = scoped_get(db, EvaluationRubricVersion, ctx.org.id, version_id)
        if v.status != "draft":
            raise HTTPException(status_code=409, detail="A published rubric version cannot be changed. Create a new draft.")
        return v

    @r.patch("/rubric-versions/{version_id}")
    def patch_version(version_id: str, body: VersionPatch, request: Request,
                      ctx: OrgContext = Depends(org_access("rubrics.manage")), db: Session = Depends(get_db)):
        v = draft(db, ctx, version_id)
        criteria = [c.model_dump() for c in body.criteria] if body.criteria is not None else v.criteria
        scale = body.scale_max if body.scale_max is not None else v.scale_max
        turns = body.min_trainee_turns if body.min_trainee_turns is not None else v.min_trainee_turns
        instr = body.scoring_instructions if body.scoring_instructions is not None else v.scoring_instructions
        check_version(criteria, scale, turns, instr)
        v.criteria, v.scale_max, v.min_trainee_turns, v.scoring_instructions = criteria, scale, turns, instr
        v.updated_at = utcnow()
        audit(db, request, "rubric.draft_updated", actor=ctx.user, organization_id=ctx.org.id,
              target_type="rubric_version", target_id=v.id)
        db.commit()
        return version_out(v)

    @r.delete("/rubric-versions/{version_id}")
    def discard_version(version_id: str, request: Request, ctx: OrgContext = Depends(org_access("rubrics.manage")),
                        db: Session = Depends(get_db)):
        v = draft(db, ctx, version_id)
        if v.version == 1:
            raise HTTPException(status_code=409, detail="The first version cannot be discarded; archive the rubric instead.")
        db.delete(v)
        audit(db, request, "rubric.draft_discarded", actor=ctx.user, organization_id=ctx.org.id,
              target_type="rubric_version", target_id=version_id)
        db.commit()
        return {"ok": True}

    @r.post("/rubric-versions/{version_id}/publish")
    def publish_version(version_id: str, request: Request, ctx: OrgContext = Depends(org_access("rubrics.manage")),
                        db: Session = Depends(get_db)):
        v = draft(db, ctx, version_id)
        check_version(v.criteria, v.scale_max, v.min_trainee_turns, v.scoring_instructions)
        now = utcnow()
        n = db.execute(update(EvaluationRubricVersion).where(
            EvaluationRubricVersion.id == v.id, EvaluationRubricVersion.status == "draft").values(
            status="published", weights={c["key"]: c["weight"] for c in v.criteria}, published_at=now,
            published_by=ctx.user.id, updated_at=now)).rowcount
        if n != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="This version was already published.")
        audit(db, request, "rubric.published", actor=ctx.user, organization_id=ctx.org.id,
              target_type="rubric_version", target_id=v.id, details={"version": v.version})
        db.commit()
        db.expire_all()
        return version_out(db.get(EvaluationRubricVersion, version_id))

    @r.put("/scenarios/{scenario_id}/rubric")
    def set_scenario_rubric(scenario_id: str, body: ScenarioRubricIn, request: Request,
                            ctx: OrgContext = Depends(org_access("scenarios.manage")), db: Session = Depends(get_db)):
        sc = scoped_get(db, TrainingScenario, ctx.org.id, scenario_id)
        if body.rubric_id:
            scoped_get(db, EvaluationRubric, ctx.org.id, body.rubric_id)
        sc.rubric_id = body.rubric_id or None
        audit(db, request, "scenario.rubric_set", actor=ctx.user, organization_id=ctx.org.id,
              target_type="scenario", target_id=sc.id, details={"rubric_id": sc.rubric_id})
        db.commit()
        return {"scenario_id": sc.id, "rubric_id": sc.rubric_id}

    # ---------- organization settings ----------
    def settings_out(db: Session, org_id: str) -> dict:
        st = db.get(TrainingOrgSettings, org_id)
        lim = db.get(TrainingOrgLimits, org_id)
        return {"recording": recordings.org_policy(db, org_id),
                "default_rubric_id": st.default_rubric_id if st else None,
                "evaluation": {"allowed": bool(lim and lim.evaluation_enabled),
                               **{k: v for k, v in intelligence.evaluation_status(db, org_id).items()
                                  if k in ("reason", "budget")},
                               "evaluator_configured": intelligence.evaluator is not None,
                               "active": bool(lim and lim.evaluation_enabled and intelligence.evaluator is not None),
                               "evaluator": getattr(intelligence.evaluator, "provider", None),
                               "model": getattr(intelligence.evaluator, "model", None),
                               "evaluator_version": EVALUATOR_VERSION},
                "provider_lookups": intelligence.attempts_provider is not None,
                "phone_otp": training_otp_available(),
                "practice_notice": {"text": (st.practice_notice_text or "") if st else "",
                                    "version": st.practice_notice_version if st else None},
                "retention": retention_out(db, org_id, st)}

    def retention_out(db: Session, org_id: str, st) -> dict:
        last = db.scalars(select(RetentionRun).where(RetentionRun.organization_id == org_id)
                          .order_by(RetentionRun.started_at.desc())).first()
        s = request_settings()
        return {"transcript_retention_days": st.transcript_retention_days if st else None,
                "recording_retention_days": st.recording_retention_days if st else 30,
                "legal_hold": bool(st and st.legal_hold), "legal_hold_reason": st.legal_hold_reason if st else None,
                "legal_hold_set_at": iso(st.legal_hold_set_at) if st else None,
                "enforcement_enabled": bool(s and s.retention_enforcement_enabled),
                "platform": {"webhook_payload_days": s.training_webhook_payload_days if s else None,
                             "browser_token_days": s.browser_token_retention_days if s else None,
                             "phone_challenge_days": s.phone_challenge_retention_days if s else None},
                "last_run": None if last is None else {"status": last.status, "enforced": last.enforced,
                                                       "counts": last.counts, "started_at": iso(last.started_at)}}

    def request_settings():
        return getattr(intelligence, "s", None)

    def training_otp_available() -> bool:
        return getattr(intelligence, "otp_sender", None) is not None

    @r.get("/training/settings")
    def get_settings(ctx: OrgContext = Depends(org_access("training.view")), db: Session = Depends(get_db)):
        return settings_out(db, ctx.org.id)

    @r.put("/training/settings")
    def put_settings(body: SettingsIn, request: Request, ctx: OrgContext = Depends(org_access("recordings.manage")),
                     db: Session = Depends(get_db)):
        st = db.get(TrainingOrgSettings, ctx.org.id)
        if st is None:
            st = TrainingOrgSettings(organization_id=ctx.org.id, recording_enabled=False, recording_retention_days=30,
                                     consent_text="")
            db.add(st)
        if body.default_rubric_id:
            scoped_get(db, EvaluationRubric, ctx.org.id, body.default_rubric_id)
            st.default_rubric_id = body.default_rubric_id
        if body.clear_default_rubric:
            st.default_rubric_id = None
        if body.consent_text is not None:
            st.consent_text = body.consent_text.strip()
            st.consent_version = consent_version(st.consent_text) if st.consent_text else None
        if body.recording_retention_days is not None:
            st.recording_retention_days = body.recording_retention_days
        if body.storage_provider is not None:
            choice = body.storage_provider.strip().lower()
            if choice not in recordings.allowed_providers():
                raise HTTPException(status_code=422, detail="That recording provider is not allowed by the platform.")
            st.storage_provider = choice
        if body.recording_enabled is not None:
            if body.recording_enabled and not st.consent_version:
                raise HTTPException(status_code=422, detail="Write the consent notice trainees must accept first.")
            st.recording_enabled = body.recording_enabled
        if body.practice_notice_text is not None:
            st.practice_notice_text = body.practice_notice_text.strip() or None
            st.practice_notice_version = consent_version(st.practice_notice_text) if st.practice_notice_text else None
        if body.keep_transcripts:
            st.transcript_retention_days = None
        elif body.transcript_retention_days is not None:
            st.transcript_retention_days = body.transcript_retention_days
        if body.legal_hold is not None and body.legal_hold != bool(st.legal_hold):
            if body.legal_hold and not (body.legal_hold_reason or "").strip():
                raise HTTPException(status_code=422, detail="Give a reason for the legal hold.")
            st.legal_hold = body.legal_hold
            st.legal_hold_reason = body.legal_hold_reason.strip() if body.legal_hold else None
            st.legal_hold_set_by, st.legal_hold_set_at = ctx.user.id, utcnow()
            audit(db, request, "training.legal_hold_" + ("set" if body.legal_hold else "released"), actor=ctx.user,
                  organization_id=ctx.org.id, target_type="organization", target_id=ctx.org.id)
        st.updated_by, st.updated_at = ctx.user.id, utcnow()
        audit(db, request, "training.settings_changed", actor=ctx.user, organization_id=ctx.org.id,
              target_type="organization", target_id=ctx.org.id,
              details=body.model_dump(exclude_none=True, exclude={"consent_text", "practice_notice_text"}) |
              ({"consent_version": st.consent_version} if body.consent_text is not None else {}) |
              ({"practice_notice_version": st.practice_notice_version} if body.practice_notice_text is not None else {}))
        db.commit()
        return settings_out(db, ctx.org.id)

    # ---------- retention ----------
    @r.get("/training/retention")
    def retention_report(ctx: OrgContext = Depends(org_access("recordings.manage")), db: Session = Depends(get_db)):
        """The organization's retention settings, what is due now (nothing is changed) and recent runs."""
        from .retention import RetentionService
        svc = RetentionService(intelligence.s, recordings)
        st = db.get(TrainingOrgSettings, ctx.org.id)
        return {**retention_out(db, ctx.org.id, st), "due_now": svc.preview(ctx.org.id)["counts"],
                "runs": svc.latest(db, ctx.org.id)}

    # ---------- scorecard ----------
    @r.get("/training/sessions/{session_id}/scorecard")
    def scorecard(session_id: str, ctx: OrgContext = Depends(org_access("training.self")),
                  db: Session = Depends(get_db)):
        """Everything about one finished session. Missing pieces are reported as missing, with the reason."""
        sess = owner_or(db, ctx, session_id, "training.view")
        t = db.scalars(select(TrainingTranscript).where(TrainingTranscript.session_id == sess.id)).first()
        jobs = {j.kind: j for j in db.scalars(select(EvaluationJob).where(EvaluationJob.session_id == sess.id))}

        def job_state(kind):
            j = jobs.get(kind)
            return None if j is None else {"status": j.status, "attempts": j.attempts, "error_code": j.error_code}
        transcript = {"status": "not_available", "reason": "The trainee did not talk to the agent." if not practised(sess)
                      else "Waiting for the provider's transcript.", "job": job_state("transcript"), "turns": []}
        if t is not None:
            transcript = {"status": t.status, "reason": t.status_reason, "source": t.source, "language": t.language,
                          "text_variant": t.text_variant, "turn_count": t.turn_count, "job": job_state("transcript"),
                          "turns": [{"n": x.sequence_number, "speaker": x.speaker, "text": x.text,
                                     "start_ms": x.start_ms, "end_ms": x.end_ms} for x in transcript_turns(db, t.id)]}
            if t.purged_at is not None:
                transcript.update(status="removed", purged_at=iso(t.purged_at),
                                  reason="Removed under the organization's retention policy.")
        evals = db.scalars(select(TrainingEvaluation).where(TrainingEvaluation.session_id == sess.id)
                           .order_by(TrainingEvaluation.evaluated_at.desc())).all()
        versions = {v.id: v for v in db.scalars(select(EvaluationRubricVersion).where(
            EvaluationRubricVersion.id.in_({e.rubric_version_id for e in evals})))} if evals else {}
        rnames = {x.id: x.name for x in db.scalars(select(EvaluationRubric).where(
            EvaluationRubric.id.in_({v.rubric_id for v in versions.values()})))} if versions else {}
        shown = [evaluation_out(e, versions.get(e.rubric_version_id),
                                rnames.get(versions[e.rubric_version_id].rubric_id) if e.rubric_version_id in versions else None)
                 for e in evals]
        current = next((e for e in shown if e["status"] != "failed"), shown[0] if shown else None)
        ej = job_state("evaluation")
        lim = db.get(TrainingOrgLimits, ctx.org.id)
        if current is None:
            reason = ("Evaluation is not switched on for this organization." if not (lim and lim.evaluation_enabled)
                      else "No evaluator is configured." if intelligence.evaluator is None
                      else "No published rubric applies to this scenario." if ej and ej["error_code"] == "no_rubric"
                      else (intelligence.evaluation_status(db, ctx.org.id)["reason"] or
                            "The evaluation budget was used up when this session ended.")
                      if ej and ej["error_code"] == "budget_exhausted"
                      else "Waiting for the transcript." if t is None or ej is None or ej["status"] in ("queued", "running")
                      else "Not evaluated.")
            evaluation = {"status": "not_evaluated", "reason": reason, "job": ej}
        else:
            evaluation = {**current, "job": ej}
        rec = db.scalars(select(TrainingRecording).where(TrainingRecording.session_id == sess.id)).first()
        policy = recordings.org_policy(db, ctx.org.id)
        recording = {"status": rec.status if rec else "none",
                     "reason": rec.status_reason if rec and rec.status_reason else
                     (None if rec else policy["reason"] or ("The trainee did not consent to recording."
                                                            if not sess.recording_consent_reference else None)),
                     "duration_seconds": rec.duration_seconds if rec else None,
                     "can_play": bool(rec and rec.status == "stored" and recordings.provider_for_recording(rec) is not None and
                                      (sess.user_id == ctx.user.id or has_permission(ctx.role, "recordings.view"))),
                     "retention_until": iso(rec.retention_until) if rec else None}
        agent = db.get(Agent, sess.agent_id)
        sc = db.get(TrainingScenario, sess.scenario_id) if sess.scenario_id else None
        adjustments = db.scalars(select(TrainingUsageAdjustment).where(TrainingUsageAdjustment.session_id == sess.id)).all()
        return {
            "session": {"id": sess.id, "user_id": sess.user_id, "agent_id": sess.agent_id,
                        "agent_name": agent.name if agent else None, "scenario_id": sess.scenario_id,
                        "scenario_name": sc.name if sc else None, "channel": sess.channel, "status": sess.status,
                        "failure_code": sess.failure_code, "created_at": iso(sess.created_at),
                        "connected_at": iso(sess.connected_at), "ended_at": iso(sess.ended_at),
                        "duration_seconds": sess.duration_seconds, "practised": practised(sess)},
            "provider": {"status": sess.provider_status, "duration_seconds": sess.provider_duration_seconds,
                         "reconciliation_status": sess.reconciliation_status, "reconciled_at": iso(sess.reconciled_at)},
            "usage": {"reserved_seconds": sess.max_duration_seconds, "billed_seconds": sess.billable_seconds,
                      "adjustment_seconds": sum(a.delta for a in adjustments),
                      "quota_seconds": (sess.billable_seconds or 0) + sum(a.delta for a in adjustments),
                      "provider_reported_seconds": sess.provider_duration_seconds,
                      "provider_billing": None, "provider_billing_note":
                      "Sarvam does not report per-call billing; its invoice is the source for that."},
            "transcript": transcript, "evaluation": evaluation,
            "other_evaluations": [e for e in shown if current is None or e["id"] != current["id"]],
            "recording": recording,
        }

    # ---------- recordings ----------
    @r.post("/training/sessions/{session_id}/recording/playback")
    def playback(session_id: str, request: Request, ctx: OrgContext = Depends(org_access("training.self")),
                 db: Session = Depends(get_db)):
        sess = owner_or(db, ctx, session_id, "recordings.view")
        rec = db.scalars(select(TrainingRecording).where(TrainingRecording.session_id == sess.id,
                                                         TrainingRecording.organization_id == ctx.org.id)).first()
        if rec is None or rec.status != "stored" or recordings.provider_for_recording(rec) is None:
            raise HTTPException(status_code=404, detail="No recording is available for this session.")
        request.app.state.limiter.check(f"recording-play:{ctx.user.id}", 60, 3600)
        url = recordings.playback_url(rec)
        audit(db, request, "training.recording_played", actor=ctx.user, organization_id=ctx.org.id,
              target_type="training_session", target_id=sess.id)
        db.commit()
        from .recordings import PLAYBACK_TTL_SECONDS
        return {"url": url, "expires_in_seconds": PLAYBACK_TTL_SECONDS}

    @r.delete("/training/sessions/{session_id}/recording")
    def delete_recording(session_id: str, request: Request, ctx: OrgContext = Depends(org_access("recordings.manage")),
                         db: Session = Depends(get_db)):
        sess = scoped_get(db, TrainingSession, ctx.org.id, session_id)
        rec = db.scalars(select(TrainingRecording).where(TrainingRecording.session_id == sess.id)).first()
        if rec is None or rec.status != "stored":
            raise HTTPException(status_code=404, detail="No stored recording for this session.")
        try:
            recordings.delete(db, rec, "Deleted by an admin.")
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=503, detail="The recording could not be deleted from storage. Try again later.",
                                headers={"X-Error-Code": getattr(exc, "code", "store_failed")})
        audit(db, request, "training.recording_deleted", actor=ctx.user, organization_id=ctx.org.id,
              target_type="training_session", target_id=sess.id)
        db.commit()
        return {"ok": True}

    # ---------- re-run ----------
    @r.post("/training/sessions/{session_id}/evaluate")
    def evaluate_again(session_id: str, body: EvaluateIn, request: Request,
                       ctx: OrgContext = Depends(org_access("evaluations.manage")), db: Session = Depends(get_db)):
        sess = scoped_get(db, TrainingSession, ctx.org.id, session_id)
        if body.rubric_version_id:
            v = scoped_get(db, EvaluationRubricVersion, ctx.org.id, body.rubric_version_id)
            if v.status != "published":
                raise HTTPException(status_code=409, detail="Only a published rubric version can be used.")
        if not intelligence.evaluation_on(db, ctx.org.id):
            raise HTTPException(status_code=409, detail="Evaluation is not available for this organization.")
        queued = enqueue(db, sess, "evaluation", {"rubric_version_id": body.rubric_version_id} if body.rubric_version_id
                         else {}, reset=True)
        if not queued:
            raise HTTPException(status_code=409, detail="An evaluation of this session is already in progress.")
        audit(db, request, "training.evaluation_requested", actor=ctx.user, organization_id=ctx.org.id,
              target_type="training_session", target_id=sess.id, details={"rubric_version_id": body.rubric_version_id})
        db.commit()
        return {"queued": True}

    @r.post("/training/sessions/{session_id}/reconcile")
    def reconcile_again(session_id: str, request: Request, ctx: OrgContext = Depends(org_access("evaluations.manage")),
                        db: Session = Depends(get_db)):
        sess = scoped_get(db, TrainingSession, ctx.org.id, session_id)
        if sess.status not in ("failed", "timed_out", "completed", "cancelled"):
            raise HTTPException(status_code=409, detail="This session has not ended yet.")
        if sess.reconciliation_status in ("matched", "corrected"):
            raise HTTPException(status_code=409, detail="This session is already reconciled.")
        enqueue(db, sess, "reconcile", reset=True)
        audit(db, request, "training.reconcile_requested", actor=ctx.user, organization_id=ctx.org.id,
              target_type="training_session", target_id=sess.id)
        db.commit()
        return {"queued": True}

    # ---------- progress and analytics ----------
    @r.get("/my/training/progress")
    def my_progress(ctx: OrgContext = Depends(org_access("training.self")), db: Session = Depends(get_db)):
        return progress_for(db, ctx.org.id, ctx.user.id)

    @r.get("/training/analytics/trainees/{user_id}")
    def trainee_progress(user_id: str, ctx: OrgContext = Depends(org_access("training.view")),
                         db: Session = Depends(get_db)):
        m = db.scalars(select(Membership).where(Membership.organization_id == ctx.org.id,
                                                Membership.user_id == user_id)).first()
        if m is None:
            raise HTTPException(status_code=404, detail="Not found.")
        u = db.get(User, user_id)
        return {"user": {"id": u.id, "email": u.email, "name": u.name}, **progress_for(db, ctx.org.id, user_id)}

    @r.get("/training/analytics")
    def analytics(days: int = 30, team_id: str = "", agent_id: str = "", page: int = 1, page_size: int = 100,
                  ctx: OrgContext = Depends(org_access("training.view")), db: Session = Depends(get_db)):
        days = min(max(days, 1), 365)
        page, page_size = max(page, 1), min(max(page_size, 1), 500)
        since = utcnow() - timedelta(days=days)
        if team_id:
            scoped_get(db, Team, ctx.org.id, team_id)
        a = OrgAnalytics(db, ctx.org.id, since, team_id, agent_id)
        trainees, total = a.trainees(page_size, (page - 1) * page_size)
        return {
            "period_days": days, "since": iso(since), "totals": a.totals(), "participation": a.participation(),
            "score_distribution": a.distribution(), "by_channel": a.channels(), "trainees": trainees,
            "trainees_page": {"page": page, "page_size": page_size, "total": total},
            "teams": a.teams(), "agents": a.agents(), "scenarios": a.scenarios(),
            "skills": skill_table(db, a.scored_evaluations()),
            "rules": "Averages use only sessions with a completed evaluation (the latest one per session). "
                     "A practice session is one where the trainee talked to the agent.",
        }

    @r.get("/training/analytics/export.csv")
    def analytics_export(request: Request, days: int = 30, team_id: str = "", agent_id: str = "",
                         kind: str = "sessions", ctx: OrgContext = Depends(org_access("training.view")),
                         db: Session = Depends(get_db)):
        """CSV of this organization's sessions or trainees for the period. Cells that a spreadsheet would run
        as a formula are prefixed with a quote. Every export is audited."""
        if kind not in ("sessions", "trainees"):
            raise HTTPException(status_code=422, detail="kind must be sessions or trainees.")
        request.app.state.limiter.check(f"analytics-export:{ctx.user.id}", 30, 3600)
        days = min(max(days, 1), 365)
        if team_id:
            scoped_get(db, Team, ctx.org.id, team_id)
        a = OrgAnalytics(db, ctx.org.id, utcnow() - timedelta(days=days), team_id, agent_id)
        audit(db, request, "training.analytics_exported", actor=ctx.user, organization_id=ctx.org.id,
              target_type="organization", target_id=ctx.org.id,
              details={"kind": kind, "days": days, "team_id": team_id or None, "agent_id": agent_id or None})
        db.commit()
        if kind == "sessions":
            lines = csv_lines(SESSION_HEADER, a.session_rows())
        else:
            def trainee_rows():
                offset = 0
                while True:
                    rows, _ = a.trainees(500, offset)
                    if not rows:
                        return
                    for t in rows:
                        yield [t[k] for k in ("user_id", "email", "name", "sessions", "practice_sessions", "evaluated",
                                              "average_score", "practice_minutes", "last_session_at")]
                    offset += 500
            lines = csv_lines(TRAINEE_HEADER, trainee_rows())
        name = f"training-{kind}-{utcnow():%Y%m%d}.csv"
        return StreamingResponse(lines, media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"',
                                          "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    # ---------- phone verification codes ----------
    def code_hash(challenge_id: str, code: str) -> str:
        return hmac.new(challenge_id.encode(), code.encode(), hashlib.sha256).hexdigest()

    @r.post("/me/phone/verification-code")
    def send_code(request: Request, ctx: OrgContext = Depends(org_access("training.self")), db: Session = Depends(get_db)):
        """Sends a 6-digit code to the caller's saved number, when an OTP sender is configured. Without one,
        numbers are confirmed by an admin and marked so."""
        sender = getattr(intelligence, "otp_sender", None)
        if sender is None:
            raise HTTPException(status_code=503, detail="Codes by message are not available. Ask an admin to confirm your number.",
                                headers={"X-Error-Code": "otp_unavailable"})
        request.app.state.limiter.check(f"otp-send:{ctx.user.id}", 3, 3600)
        user = db.get(User, ctx.user.id)
        if not user.phone_e164:
            raise HTTPException(status_code=409, detail="Save your phone number first.")
        now = utcnow()
        db.execute(update(PhoneVerificationChallenge).where(
            PhoneVerificationChallenge.membership_id == ctx.membership.id,
            PhoneVerificationChallenge.consumed_at.is_(None)).values(consumed_at=now))
        code = f"{secrets.randbelow(10 ** 6):06d}"
        ch = PhoneVerificationChallenge(organization_id=ctx.org.id, membership_id=ctx.membership.id, user_id=user.id,
                                        phone_e164=user.phone_e164, code_hash="", attempts=0,
                                        max_attempts=OTP_MAX_ATTEMPTS, expires_at=now + OTP_TTL, created_at=now)
        db.add(ch)
        db.flush()
        ch.code_hash = code_hash(ch.id, code)
        if not sender.send(user.phone_e164, code):
            db.rollback()
            raise HTTPException(status_code=502, detail="Could not send the code. Try again later.")
        audit(db, request, "member.phone_code_sent", actor=user, organization_id=ctx.org.id,
              target_type="membership", target_id=ctx.membership.id)
        db.commit()
        return {"sent": True, "expires_in_seconds": int(OTP_TTL.total_seconds())}

    @r.post("/me/phone/verify")
    def verify_code(body: OtpVerifyIn, request: Request, ctx: OrgContext = Depends(org_access("training.self")),
                    db: Session = Depends(get_db)):
        request.app.state.limiter.check(f"otp-verify:{ctx.user.id}", 10, 3600)
        now = utcnow()
        ch = db.scalars(select(PhoneVerificationChallenge).where(
            PhoneVerificationChallenge.membership_id == ctx.membership.id,
            PhoneVerificationChallenge.consumed_at.is_(None)).order_by(PhoneVerificationChallenge.created_at.desc())).first()
        if ch is None or ch.expires_at < now or ch.attempts >= ch.max_attempts:
            raise HTTPException(status_code=409, detail="This code has expired. Ask for a new one.")
        n = db.execute(update(PhoneVerificationChallenge).where(
            PhoneVerificationChallenge.id == ch.id, PhoneVerificationChallenge.attempts < ch.max_attempts,
            PhoneVerificationChallenge.consumed_at.is_(None)).values(attempts=PhoneVerificationChallenge.attempts + 1)).rowcount
        db.commit()
        user = db.get(User, ctx.user.id)
        if n != 1 or not hmac.compare_digest(ch.code_hash, code_hash(ch.id, body.code.strip())):
            raise HTTPException(status_code=422, detail="That code is not right.")
        if user.phone_e164 != ch.phone_e164:
            raise HTTPException(status_code=409, detail="Your number changed after the code was sent. Ask for a new one.")
        m = db.get(Membership, ctx.membership.id)
        ch.consumed_at = now
        m.verified_phone_e164, m.phone_verified_at, m.phone_verified_by = ch.phone_e164, now, None
        m.phone_verification_method = "otp"
        audit(db, request, "member.phone_verified", actor=user, organization_id=ctx.org.id,
              target_type="membership", target_id=m.id, details={"method": "otp"})
        db.commit()
        return {"verified": True, "method": "otp"}

    return r
