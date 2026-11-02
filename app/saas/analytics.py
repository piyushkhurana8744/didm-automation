"""Training analytics aggregated in SQL, and CSV export.

Same rules as before (intelligence_api.py module docstring): a practice session is one where the trainee
talked to the agent; scores come only from each session's latest completed evaluation, so sessions that
were not evaluated, or had insufficient evidence, never enter an average. Every query is filtered by the
organization first. Indexes used: ix_training_sessions_org_created, ix_training_evaluations_org_evaluated
and the session_id index on training_evaluations.
"""
import csv
import io

from sqlalchemy import and_, case, distinct, func, or_, select

from .models import (Agent, Membership, Team, TeamMember, TrainingEvaluation, TrainingScenario, TrainingSession,
                     User)
from .permissions import TRAINEE

S = TrainingSession
BUCKETS = ((0, 39, "0-39"), (40, 59, "40-59"), (60, 74, "60-74"), (75, 89, "75-89"), (90, 100, "90-100"))
PRACTISED = or_(S.connected_at.isnot(None),
                and_(S.provider_status == "connected", func.coalesce(S.provider_duration_seconds, 0) > 0))
SECONDS = case((PRACTISED, func.coalesce(S.provider_duration_seconds, S.duration_seconds, 0)), else_=0)


def latest_completed(org_id: str):
    """One row per session: its latest completed evaluation."""
    E = TrainingEvaluation
    rn = func.row_number().over(partition_by=E.session_id, order_by=(E.evaluated_at.desc(), E.id.desc())).label("rn")
    inner = select(E.session_id, E.overall_score, E.id.label("evaluation_id"), rn).where(
        E.organization_id == org_id, E.status == "completed").subquery()
    return select(inner.c.session_id, inner.c.overall_score, inner.c.evaluation_id).where(inner.c.rn == 1).subquery()


def _num(v):
    return None if v is None else round(float(v))


def _mins(v):
    return round(float(v or 0) / 60, 1)


class OrgAnalytics:
    def __init__(self, db, org_id: str, since, team_id: str = "", agent_id: str = ""):
        self.db, self.org_id = db, org_id
        self.latest = latest_completed(org_id)
        self.cond = [S.organization_id == org_id, S.created_at >= since]
        self.team_users = None
        if team_id:
            self.team_users = select(TeamMember.user_id).where(TeamMember.team_id == team_id,
                                                               TeamMember.removed_at.is_(None))
            self.cond.append(S.user_id.in_(self.team_users))
        if agent_id:
            self.cond.append(S.agent_id == agent_id)
        L = self.latest
        self.scored = and_(PRACTISED, L.c.session_id.isnot(None))
        self.measures = [func.count(S.id).label("sessions"),
                         func.coalesce(func.sum(case((PRACTISED, 1), else_=0)), 0).label("practice_sessions"),
                         func.coalesce(func.sum(case((self.scored, 1), else_=0)), 0).label("evaluated"),
                         func.avg(case((self.scored, L.c.overall_score))).label("average_score"),
                         func.coalesce(func.sum(SECONDS), 0).label("seconds"),
                         func.count(distinct(case((PRACTISED, S.user_id)))).label("active_trainees"),
                         func.max(S.created_at).label("last_session_at")]

    def _q(self, *cols):
        return (select(*cols, *self.measures).select_from(S).outerjoin(self.latest, self.latest.c.session_id == S.id)
                .where(*self.cond))

    def totals(self) -> dict:
        r = self.db.execute(self._q()).one()
        return {"sessions": r.sessions, "practice_sessions": int(r.practice_sessions), "evaluated_sessions": int(r.evaluated),
                "average_score": _num(r.average_score), "practice_minutes": _mins(r.seconds),
                "active_trainees": r.active_trainees}

    def trainees(self, limit: int, offset: int) -> tuple[list[dict], int]:
        avg_col = self.measures[3]
        q = (self._q(S.user_id, User.email, User.name).join(User, User.id == S.user_id)
             .group_by(S.user_id, User.email, User.name)
             .order_by(case((avg_col.is_(None), 1), else_=0), avg_col.desc(), User.email))
        total = self.db.scalar(select(func.count(distinct(S.user_id))).where(*self.cond))
        rows = self.db.execute(q.limit(limit).offset(offset)).all()
        return [{"user_id": r.user_id, "email": r.email, "name": r.name, "sessions": r.sessions,
                 "practice_sessions": int(r.practice_sessions), "evaluated": int(r.evaluated),
                 "average_score": _num(r.average_score), "practice_minutes": _mins(r.seconds),
                 "last_session_at": r.last_session_at.isoformat() if r.last_session_at else None} for r in rows], total

    def agents(self) -> list[dict]:
        statuses = ("completed", "failed", "timed_out", "cancelled")
        extra = [func.coalesce(func.sum(case((S.status == st, 1), else_=0)), 0).label(st) for st in statuses]
        names = dict(self.db.execute(select(Agent.id, Agent.name).where(Agent.organization_id == self.org_id)).all())
        rows = self.db.execute(self._q(S.agent_id, *extra).group_by(S.agent_id)).all()
        return [{"agent_id": r.agent_id, "agent_name": names.get(r.agent_id), "sessions": r.sessions,
                 **{st: int(getattr(r, st)) for st in statuses}, "practice_sessions": int(r.practice_sessions),
                 "evaluated": int(r.evaluated), "average_score": _num(r.average_score),
                 "practice_minutes": _mins(r.seconds)} for r in rows]

    def scenarios(self) -> list[dict]:
        names = dict(self.db.execute(select(TrainingScenario.id, TrainingScenario.name)
                                     .where(TrainingScenario.organization_id == self.org_id)).all())
        rows = self.db.execute(self._q(S.scenario_id).where(S.scenario_id.isnot(None)).group_by(S.scenario_id)).all()
        return [{"scenario_id": r.scenario_id, "scenario_name": names.get(r.scenario_id),
                 "practice_sessions": int(r.practice_sessions), "trainees": r.active_trainees,
                 "average_score": _num(r.average_score)} for r in rows]

    def channels(self) -> list[dict]:
        rows = self.db.execute(self._q(S.channel).group_by(S.channel)).all()
        return [{"channel": r.channel, "sessions": r.sessions, "practice_minutes": _mins(r.seconds)} for r in rows]

    def teams(self) -> list[dict]:
        TM = TeamMember
        teams = self.db.execute(select(Team.id, Team.name).where(Team.organization_id == self.org_id,
                                                                 Team.archived_at.is_(None))).all()
        members = dict(self.db.execute(select(TM.team_id, func.count(TM.user_id)).join(Team, Team.id == TM.team_id)
                                       .where(Team.organization_id == self.org_id, TM.removed_at.is_(None))
                                       .group_by(TM.team_id)).all())
        rows = {r.team_id: r for r in self.db.execute(
            self._q(TM.team_id).join(TM, and_(TM.user_id == S.user_id, TM.removed_at.is_(None)))
            .join(Team, and_(Team.id == TM.team_id, Team.organization_id == self.org_id, Team.archived_at.is_(None)))
            .group_by(TM.team_id)).all()}
        out = []
        for tid, name in teams:
            r = rows.get(tid)
            out.append({"team_id": tid, "name": name, "members": members.get(tid, 0),
                        "active_trainees": r.active_trainees if r else 0,
                        "practice_sessions": int(r.practice_sessions) if r else 0,
                        "evaluated": int(r.evaluated) if r else 0, "average_score": _num(r.average_score) if r else None})
        return out

    def distribution(self) -> dict:
        L = self.latest
        bucket = case(*[(and_(L.c.overall_score >= lo, L.c.overall_score <= hi), label) for lo, hi, label in BUCKETS])
        rows = dict(self.db.execute(select(bucket, func.count()).select_from(S).join(L, L.c.session_id == S.id)
                                    .where(*self.cond, PRACTISED).group_by(bucket)).all())
        return {label: int(rows.get(label, 0)) for _, _, label in BUCKETS}

    def scored_evaluations(self):
        """criterion_results of the scored evaluations, for the skill table (aggregated in Python because
        the criteria live in JSON, which SQLite and PostgreSQL query differently)."""
        L = self.latest
        return self.db.execute(select(TrainingEvaluation.rubric_version_id, TrainingEvaluation.criterion_results)
                               .join(L, L.c.evaluation_id == TrainingEvaluation.id).join(S, S.id == L.c.session_id)
                               .where(*self.cond, PRACTISED)).all()

    def participation(self) -> dict:
        M = Membership
        trainees = select(M.user_id).where(M.organization_id == self.org_id, M.role == TRAINEE, M.status == "active")
        if self.team_users is not None:
            trainees = trainees.where(M.user_id.in_(self.team_users))
        n = self.db.scalar(select(func.count()).select_from(trainees.subquery()))
        practised = self.db.scalar(select(func.count(distinct(S.user_id))).where(*self.cond, PRACTISED,
                                                                                 S.user_id.in_(trainees)))
        return {"trainees": n, "practised": practised}

    def session_rows(self, batch: int = 1000):
        """Every session in the period, for the CSV export, read in batches by keyset."""
        L = self.latest
        agents = dict(self.db.execute(select(Agent.id, Agent.name).where(Agent.organization_id == self.org_id)).all())
        scen = dict(self.db.execute(select(TrainingScenario.id, TrainingScenario.name)
                                    .where(TrainingScenario.organization_id == self.org_id)).all())
        last = None
        while True:
            q = (select(S.id, S.created_at, S.channel, S.status, S.agent_id, S.scenario_id, User.email, User.name,
                        PRACTISED.label("practised"), SECONDS.label("seconds"),
                        case((PRACTISED, L.c.overall_score)).label("score"))
                 .join(User, User.id == S.user_id).outerjoin(L, L.c.session_id == S.id).where(*self.cond))
            if last is not None:
                q = q.where(or_(S.created_at > last[0], and_(S.created_at == last[0], S.id > last[1])))
            rows = self.db.execute(q.order_by(S.created_at, S.id).limit(batch)).all()
            if not rows:
                return
            for r in rows:
                yield [r.id, r.created_at.isoformat(), r.email, r.name or "", agents.get(r.agent_id, ""),
                       scen.get(r.scenario_id, "") if r.scenario_id else "", r.channel, r.status,
                       "yes" if r.practised else "no", _mins(r.seconds), "" if r.score is None else r.score]
            last = (rows[-1].created_at, rows[-1].id)


# ---------- CSV ----------
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v) -> str:
    """Spreadsheet formula injection: a text cell starting with = + - @ tab or CR is prefixed with a quote,
    so Excel and Sheets show it as text instead of running it. Numbers are written as numbers."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    return "'" + s if s.startswith(FORMULA_START) else s


def csv_lines(header: list[str], rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    yield buf.getvalue()
    for row in rows:
        buf.seek(0)
        buf.truncate()
        w.writerow([safe_cell(c) for c in row])
        yield buf.getvalue()


SESSION_HEADER = ["session_id", "created_at_utc", "trainee_email", "trainee_name", "agent", "scenario", "channel",
                  "status", "practised", "practice_minutes", "score"]
TRAINEE_HEADER = ["user_id", "trainee_email", "trainee_name", "sessions", "practice_sessions", "evaluated",
                  "average_score", "practice_minutes", "last_session_at_utc"]
