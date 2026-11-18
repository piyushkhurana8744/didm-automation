"""Organization-scoped outbound history and authenticated audio."""
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .auth import OrgContext, audit, get_db, org_access
from .models import Agent, OutboundCall, OutboundSyncState
from .intelligence import JobGiveUp, JobRetry
from .campaign_audio import render_audio


def build_outbound_router():
    r = APIRouter(prefix="/api/v1/organizations/{org_id}/outbound-calls")
    access = org_access("training.view")

    @r.get("")
    def history(request: Request, ctx: OrgContext = Depends(access), db: Session = Depends(get_db),
                agent_id: str = "", status: str = "", q: str = Query("", max_length=200),
                offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
        query = select(OutboundCall, Agent).join(Agent, OutboundCall.agent_id == Agent.id).where(
            OutboundCall.organization_id == ctx.org.id, Agent.organization_id == ctx.org.id)
        if agent_id:
            query = query.where(OutboundCall.agent_id == agent_id)
        if status:
            query = query.where(OutboundCall.status == status)
        if q:
            query = query.where(or_(OutboundCall.phone.contains(q, autoescape=True),
                                   OutboundCall.attempt_id.contains(q, autoescape=True)))
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.execute(query.order_by(OutboundCall.started_at.desc(), OutboundCall.id.desc())
                          .offset(offset).limit(limit)).all()
        agents = db.scalars(select(Agent).where(Agent.organization_id == ctx.org.id).order_by(Agent.name)).all()
        states = {s.agent_id: s for s in db.scalars(select(OutboundSyncState).join(
            Agent, OutboundSyncState.agent_id == Agent.id).where(Agent.organization_id == ctx.org.id))}
        return {"configured": request.app.state.outbound_history.configured(), "total": total,
                "agents": [{"id": a.id, "name": a.name, "active": a.status == "active",
                    "last_synced_at": states[a.id].last_synced_at.isoformat()+"Z" if a.id in states and states[a.id].last_synced_at else None,
                    "error": states[a.id].error if a.id in states else None,
                    "catching_up": bool(a.id in states and states[a.id].offset)}
                    for a in agents if "phone" in (a.channels or [])],
                "items": [{"id": c.id, "name": c.phone or a.name, "phone": c.phone,
                    "agent_name": a.name, "agent_id": a.id, "attempt_id": c.attempt_id,
                    "status": c.status, "state": "done" if c.finished_at else "calling", "dry_run": False,
                    "started_at": c.started_at.isoformat()+"Z", "duration": c.duration,
                    "campaign_id": c.campaign_id, "failure_reason": c.failure_reason,
                    "variables": c.variables, "transcript": c.transcript,
                    "has_interaction": bool(c.interaction_id)} for c, a in rows]}

    @r.post("/sync")
    def sync(request: Request, tasks: BackgroundTasks, ctx: OrgContext = Depends(access)):
        request.app.state.limiter.check(f"outbound-sync:{ctx.org.id}", 10, 60)
        service = request.app.state.outbound_history
        if not service.configured():
            raise HTTPException(409, "Configure SARVAM_API_KEY, SARVAM_ORG_ID and SARVAM_WORKSPACE_ID on the backend.")
        tasks.add_task(service.run, ctx.org.id)
        return {"configured": True, "queued": True}

    @r.get("/calls/{call_id}/recording")
    def recording(call_id: int, request: Request, ctx: OrgContext = Depends(org_access("recordings.view")),
                  db: Session = Depends(get_db), channel: Literal["both", "student", "agent", "original"] = "both"):
        row = db.execute(select(OutboundCall, Agent).join(Agent, OutboundCall.agent_id == Agent.id).where(
            OutboundCall.id == call_id, OutboundCall.organization_id == ctx.org.id,
            Agent.organization_id == ctx.org.id)).first()
        if not row:
            raise HTTPException(404, "Call not found.")
        call, agent = row
        if not call.finished_at:
            raise HTTPException(409, "Recording is available after the call ends.")
        if not call.interaction_id:
            raise HTTPException(404, "This call has no conversation recording.")
        request.app.state.limiter.check(f"outbound-recording:{ctx.user.id}", 60, 3600)
        adapter_call = SimpleNamespace(attempt_id=call.attempt_id, started_at=call.started_at,
            duration=call.duration, raw_result={"interaction_id": call.interaction_id})
        try:
            audio = request.app.state.campaign_recordings.fetch(adapter_call,
                SimpleNamespace(provider_app_id=agent.provider_app_id))
            if audio is None:
                raise HTTPException(404, "Recording is not available from Sarvam. It may still be processing or no longer retained.")
            content, mime, _ = audio
            content = render_audio(content, channel)
        except JobRetry as exc:
            raise HTTPException(503, "Sarvam recording is temporarily unavailable. Try again shortly.",
                                headers={"Retry-After": str(exc.retry_after or 60)})
        except JobGiveUp:
            raise HTTPException(502, "Sarvam returned an invalid recording.")
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        audit(db, request, "outbound.recording_accessed", actor=ctx.user,
              organization_id=ctx.org.id, target_type="outbound_call", target_id=str(call.id))
        db.commit()
        return Response(content, media_type=mime, headers={"Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="call-{call.id}-{channel}.wav"'})

    return r
