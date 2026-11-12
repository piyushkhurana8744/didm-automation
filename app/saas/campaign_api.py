"""Cookie-authenticated UI for the sequential Excel lead dialler."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select

from ..db import Batch, CallAttempt, SessionLocal
from ..excel_leads import parse_excel, sample_excel, save_upload
from ..main import _transcript_text
from .auth import OrgContext, get_db, org_access
from .models import Agent, AgentVersion
from sqlalchemy.orm import Session


def build_campaign_router(automation) -> APIRouter:
    r = APIRouter(prefix="/api/v1/organizations/{org_id}/calling-campaign")

    @r.get("")
    def status(ctx: OrgContext = Depends(org_access("training.view")), db: Session = Depends(get_db)):
        agents = db.execute(select(Agent, AgentVersion).join(AgentVersion, Agent.published_version_id == AgentVersion.id)
                            .where(Agent.organization_id == ctx.org.id, Agent.status == "active",
                                   AgentVersion.status == "published")).all()
        with SessionLocal() as db:
            calls = db.scalars(select(CallAttempt).order_by(CallAttempt.id.desc()).limit(100)).all()
            batch = db.scalars(select(Batch).order_by(Batch.id.desc())).first()
        return {"mode": "test" if automation.s.dry_run else "live",
                "agents": [{"id": a.id, "name": a.name, "app_id": a.provider_app_id,
                 "app_version": v.provider_app_version} for a, v in agents if "phone" in (a.channels or [])],
                "batch": None if not batch else {"id": batch.id, "requested": batch.requested,
                "dialled": batch.dialled, "active": batch.active, "note": batch.note,
                "agent_id": batch.agent_id, "agent_name": batch.agent_name},
                "calls": [{"id": c.id, "name": c.name, "phone": c.phone, "state": c.state,
                "status": c.status, "outcome": c.outcome, "duration": c.duration,
                "summary": c.summary or c.error, "transcript": _transcript_text(c.raw_result)} for c in calls]}

    @r.get("/sample.xlsx")
    def sample(ctx: OrgContext = Depends(org_access("training.manage"))):
        return Response(sample_excel(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="didm-leads-sample.xlsx"'})

    @r.post("/upload")
    async def upload(request: Request, ctx: OrgContext = Depends(org_access("training.manage"))):
        body = await request.body()
        if not body or len(body) > 5 * 1024 * 1024:
            raise HTTPException(413 if body else 400, "Excel file missing ya 5 MB se badi hai.")
        with SessionLocal() as db:
            active = db.scalars(select(Batch).where(Batch.active.is_(True))).first()
            calling = db.scalar(select(func.count(CallAttempt.id)).where(CallAttempt.state == "calling")) or 0
        if active or calling:
            raise HTTPException(409, "Current calling batch khatam/stop hone ke baad nayi Excel upload karein.")
        try:
            leads, rejected = await run_in_threadpool(parse_excel, body)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        upload_id = await run_in_threadpool(save_upload, leads)
        return {"ok": True, "upload_id": upload_id, "accepted": len(leads), "rejected": len(rejected),
                "rejected_rows": rejected[:100]}

    @r.post("/start")
    def start(body: dict, ctx: OrgContext = Depends(org_access("training.manage")), db: Session = Depends(get_db)):
        count = min(max(int(body.get("count", 1)), 1), 5000)
        agent_id = str(body.get("agent_id") or "")
        row = db.execute(select(Agent, AgentVersion).join(AgentVersion, Agent.published_version_id == AgentVersion.id)
                         .where(Agent.id == agent_id, Agent.organization_id == ctx.org.id,
                                Agent.status == "active", AgentVersion.status == "published")).first()
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
        result = automation.start_batch(count, agent=agent)
        if not result.get("ok"):
            raise HTTPException(409, result.get("reason", "Calling could not start."))
        return result

    @r.post("/stop")
    def stop(ctx: OrgContext = Depends(org_access("training.manage"))):
        return automation.stop()

    @r.post("/resume")
    def resume(ctx: OrgContext = Depends(org_access("training.manage"))):
        return automation.resume()

    return r
