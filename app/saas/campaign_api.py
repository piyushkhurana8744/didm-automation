"""Cookie-authenticated UI for Excel lead campaigns."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..db import Batch, CallAttempt, SessionLocal, get_flag
from ..excel_leads import parse_upload, sample_excel, save_upload, remove_upload, queue_details
from urllib.parse import unquote
from ..main import _transcript_text
from .auth import OrgContext, audit, get_db, org_access
from .intelligence import JobGiveUp, JobRetry
from .models import Agent, AgentVersion
from .agents import entitlements
from .permissions import has_permission
from sqlalchemy.orm import Session


class StartCampaign(BaseModel):
    count: int = Field(default=1, ge=1, le=5000)
    parallel_calls: int = Field(default=1, ge=1, le=10)
    agent_id: str = ""
    upload_id: str = ""
    mode: Literal["live", "test"] | None = None


def build_campaign_router(automation) -> APIRouter:
    r = APIRouter(prefix="/api/v1/organizations/{org_id}/calling-campaign")

    def campaign_access(ctx: OrgContext = Depends(org_access("campaigns.use")),
                        db: Session = Depends(get_db)):
        if not has_permission(ctx.role, "training.manage") and not any(
                "phone" in (e.agent.channels or []) for e in entitlements(db, ctx.org.id, ctx.user.id)):
            raise HTTPException(403, "An active phone agent assignment is required for Excel calling.")
        return ctx

    def available_agents(ctx, db):
        if has_permission(ctx.role, "training.manage"):
            return db.execute(select(Agent, AgentVersion).join(
                AgentVersion, Agent.published_version_id == AgentVersion.id).where(
                Agent.organization_id == ctx.org.id, Agent.status == "active",
                AgentVersion.status == "published")).all()
        return [(e.agent, e.version) for e in entitlements(db, ctx.org.id, ctx.user.id)]

    @r.get("")
    def status(ctx: OrgContext = Depends(campaign_access), db: Session = Depends(get_db)):
        agents = available_agents(ctx, db)
        with SessionLocal() as db:
            queue = queue_details(db, automation)
            stopped = automation.is_stopped(db)
            calls = db.scalars(select(CallAttempt).order_by(CallAttempt.id.desc()).limit(100)).all()
            batch = db.scalars(select(Batch).order_by(Batch.id.desc())).first()
            parallel_calls = int(get_flag(db, f"batch_parallel_{batch.id}", "1")) if batch else 1
            sources = {batch_id: get_flag(db, f"batch_file_{batch_id}", "Earlier campaign / source unavailable")
                       for batch_id in {c.batch_id for c in calls}}
            uploads = {batch_id: get_flag(db, f"batch_upload_{batch_id}", "")
                       for batch_id in sources}
        return {"mode": "test" if automation.s.dry_run else "live",
                "queue": queue, "stopped": stopped,
                "agents": [{"id": a.id, "name": a.name, "app_id": a.provider_app_id,
                 "app_version": v.provider_app_version} for a, v in agents if "phone" in (a.channels or [])],
                "batch": None if not batch else {"id": batch.id, "requested": batch.requested,
                "dialled": batch.dialled, "active": batch.active, "note": batch.note,
                "agent_id": batch.agent_id, "agent_name": batch.agent_name, "parallel_calls": parallel_calls,
                "mode": "test" if (automation.s.dry_run if batch.dry_run is None else batch.dry_run) else "live"},
                "calls": [{"id": c.id, "name": c.name, "phone": c.phone, "state": c.state,
                "filename": sources[c.batch_id], "batch_id": c.batch_id, "dry_run": c.dry_run,
                "current_upload": bool(queue and uploads[c.batch_id] == queue["id"]),
                "request_accepted": bool(c.attempt_id), "started_at": c.started_at.isoformat() + "Z",
                "status": c.status, "outcome": c.outcome, "duration": c.duration,
                "summary": c.summary or c.error, "transcript": _transcript_text(c.raw_result)} for c in calls]}

    @r.get("/sample.xlsx")
    def sample(ctx: OrgContext = Depends(campaign_access)):
        return Response(sample_excel(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="didm-leads-sample.xlsx"'})

    @r.post("/upload")
    async def upload(request: Request, ctx: OrgContext = Depends(campaign_access)):
        body = await request.body()
        if not body or len(body) > 5 * 1024 * 1024:
            raise HTTPException(413 if body else 400, "Excel/CSV file missing ya 5 MB se badi hai.")
        with SessionLocal() as db:
            active = db.scalars(select(Batch).where(Batch.active.is_(True))).first()
            calling = db.scalar(select(func.count(CallAttempt.id)).where(CallAttempt.state == "calling")) or 0
        if active or calling:
            raise HTTPException(409, "Current calling batch khatam/stop hone ke baad nayi Excel upload karein.")
        filename = unquote(request.headers.get("X-Upload-Filename", "leads.xlsx")).replace("\\", "/").split("/")[-1]
        try:
            leads, rejected = await run_in_threadpool(parse_upload, body, filename)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        def persist():
            with automation._lock:
                return save_upload(leads, filename)
        try:
            upload_id = await run_in_threadpool(persist)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return {"ok": True, "upload_id": upload_id, "accepted": len(leads), "rejected": len(rejected),
                "rejected_rows": rejected[:100]}

    @r.delete("/upload")
    def remove(ctx: OrgContext = Depends(campaign_access)):
        try:
            with automation._lock:
                remove_upload()
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return {"ok": True}

    @r.post("/start")
    def start(body: StartCampaign, ctx: OrgContext = Depends(campaign_access), db: Session = Depends(get_db)):
        count = body.count
        agent_id = body.agent_id
        row = next(((a, v) for a, v in available_agents(ctx, db) if a.id == agent_id), None)
        if not row or "phone" not in (row[0].channels or []):
            raise HTTPException(422, "Select an active published phone agent.")
        a, v = row
        config = v.configuration_snapshot or {}
        agent = {"id": a.id, "name": a.name, "app_id": a.provider_app_id,
                 "app_version": v.provider_app_version,
                 "connection_id": config.get("connection_id") or automation.s.sarvam_connection_id,
                 "agent_phone": config.get("agent_phone_number") or automation.s.sarvam_agent_phone}
        if not agent["connection_id"] or not agent["agent_phone"]:
            raise HTTPException(409, "Selected agent has no phone connection configuration.")
        with automation._lock:
            with SessionLocal() as session:
                queue = queue_details(session, automation)
            if not queue or body.upload_id != queue["id"]:
                raise HTTPException(409, "Queue badal gayi hai. Refresh karke current Excel confirm karein.")
            if not queue["ready"]:
                raise HTTPException(409, "No leads are ready to call. Upload/replace the Excel file, or review previous results and retry timing.")
            automation.resume()
            dry_run = automation.s.dry_run if body.mode is None else body.mode == "test"
            result = automation.start_batch(count, agent=agent, dry_run=dry_run,
                                            parallel_calls=min(count, body.parallel_calls))
        if not result.get("ok"):
            raise HTTPException(409, result.get("reason", "Calling could not start."))
        with SessionLocal() as session:
            attempts = session.scalars(select(CallAttempt).where(
                CallAttempt.batch_id == result["batch_id"])).all()
            if attempts and all(c.state == "start_failed" for c in attempts):
                raise HTTPException(409, "Call could not start: " + (attempts[-1].error or "Sarvam rejected the request."))
        return result

    @r.get("/calls/{call_id}/recording")
    def recording(call_id: int, request: Request, ctx: OrgContext = Depends(campaign_access),
                  db: Session = Depends(get_db), channel: Literal["both", "student", "agent", "original"] = "both"):
        # A call id alone grants no access: verify its pinned agent and organization first.
        row = db.execute(select(CallAttempt, Batch).join(Batch, CallAttempt.batch_id == Batch.id)
                         .join(Agent, Batch.agent_id == Agent.id).where(
                             CallAttempt.id == call_id, Agent.organization_id == ctx.org.id)).first()
        if row is None:
            raise HTTPException(404, "Call not found.")
        call, batch = row
        if not has_permission(ctx.role, "training.manage") and batch.agent_id not in {
                a.id for a, _ in available_agents(ctx, db)}:
            raise HTTPException(404, "Call not found.")
        if call.dry_run:
            raise HTTPException(404, "Test calls have no recording.")
        if call.state == "calling":
            raise HTTPException(409, "Call result pending. Try the recording after the call ends.")
        if call.state == "start_failed" or not batch.provider_app_id or not call.attempt_id:
            raise HTTPException(404, "No recording is available for this call.")
        request.app.state.limiter.check(f"campaign-recording:{ctx.user.id}", 60, 3600)
        try:
            audio = request.app.state.campaign_recordings.fetch(call, batch)
        except JobRetry as exc:
            raise HTTPException(503, "Recording could not be fetched from Sarvam. Try again shortly.",
                                headers={"Retry-After": str(exc.retry_after or 60)})
        except JobGiveUp:
            raise HTTPException(502, "Sarvam returned an invalid recording.")
        if audio is None:
            raise HTTPException(404, "Recording is not available from Sarvam yet. Try again shortly; unanswered calls may have no recording.")
        content, content_type, interaction_id = audio
        from .campaign_audio import render_audio
        try:
            content = render_audio(content, channel)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        call.raw_result = {**(call.raw_result or {}), "interaction_id": interaction_id}
        audit(db, request, "campaign.recording_accessed", actor=ctx.user,
              organization_id=ctx.org.id, target_type="call_attempt", target_id=str(call.id))
        db.commit()
        return Response(content, media_type=content_type, headers={
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="call-{call.id}-{channel}.wav"'})

    @r.post("/stop")
    def stop(ctx: OrgContext = Depends(campaign_access)):
        return automation.stop()

    @r.post("/resume")
    def resume(ctx: OrgContext = Depends(campaign_access)):
        return automation.resume()

    return r
