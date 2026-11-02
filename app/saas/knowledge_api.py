"""DIDM-owned knowledge authoring, offline retrieval, validation and local release preparation.

This module has no Sarvam import and no network client. File uploads remain unavailable until private storage
and a production malware scanner are configured; manual and FAQ knowledge are fully local.
"""
import hashlib
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from .auth import OrgContext, audit, get_db, org_access, scoped_get
from .models import (Agent, AgentValidationRun, AgentVersion, AgentVersionKnowledgeItem, KnowledgeChunk,
                     KnowledgeDocument, KnowledgeDocumentRevision, KnowledgeLibrary, KnowledgeSnapshot,
                     KnowledgeSnapshotItem, KnowledgeTextBlock)

WORDS = re.compile(r"[\w\u0900-\u097f]+", re.UNICODE)
STOPWORDS = {"a", "an", "and", "are", "for", "in", "is", "of", "on", "the", "to", "what", "when", "with"}
ROLES = ("ai_student_customer", "ai_admissions_counsellor")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _iso(value):
    return value.isoformat() + "Z" if value else None


def _tokens(value: str) -> set[str]:
    return {x.lower() for x in WORDS.findall(value) if len(x) > 1 and x.lower() not in STOPWORDS}


def _chunks(text: str, size: int = 180) -> list[str]:
    """Deterministic paragraph-aware word chunker for manual/FAQ content (offline, version v1)."""
    words = text.split()
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)] or [""]


class LibraryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class ManualIn(BaseModel):
    library_id: str = Field(max_length=36)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=200_000)
    kind: str = "manual"
    locale: str = Field(default="en-IN", min_length=2, max_length=30)


class AttachIn(BaseModel):
    revision_ids: list[str] = Field(default_factory=list, max_length=200)


class BehaviorIn(BaseModel):
    role: str
    persona: str = Field(default="", max_length=10_000)
    objective: str = Field(default="", max_length=10_000)
    instructions: str = Field(default="", max_length=30_000)
    languages: list[str] = Field(default_factory=lambda: ["en-IN"], min_length=1, max_length=22)
    default_language: str = Field(default="en-IN", max_length=30)
    unknown_answer: str = Field(default="I don't have approved information about that.", max_length=1000)
    escalation: str = Field(default="Offer to connect the learner with an authorized DIDM representative.",
                            max_length=2000)


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    limit: int = Field(default=5, ge=1, le=10)


def library_out(row):
    return {"id": row.id, "name": row.name, "description": row.description, "status": row.status,
            "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at)}


def document_out(row, revision=None):
    return {"id": row.id, "library_id": row.library_id, "kind": row.kind, "title": row.title,
            "status": row.status, "current_revision_id": row.current_revision_id,
            "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at),
            "revision": ({"id": revision.id, "revision_no": revision.revision_no,
                          "processing_state": revision.processing_state, "malware_state": revision.malware_state,
                          "source_locale": revision.source_locale, "sha256": revision.sha256,
                          "created_at": _iso(revision.created_at)} if revision else None)}


def build_knowledge_router(settings) -> APIRouter:
    r = APIRouter(prefix="/api/v1/organizations/{org_id}")

    def draft(db: Session, ctx: OrgContext, agent_id: str, version_id: str) -> tuple[Agent, AgentVersion]:
        agent = scoped_get(db, Agent, ctx.org.id, agent_id)
        version = db.scalars(select(AgentVersion).where(
            AgentVersion.id == version_id, AgentVersion.agent_id == agent.id,
            AgentVersion.organization_id == ctx.org.id)).first()
        if version is None:
            raise HTTPException(status_code=404, detail="Not found.")
        if version.status != "draft":
            raise HTTPException(status_code=409, detail="Published versions cannot be changed.")
        return agent, version

    @r.get("/knowledge/capabilities")
    def capabilities(ctx: OrgContext = Depends(org_access("knowledge.view"))):
        return {"manual": True, "faq": True, "offline_retrieval": True, "file_upload": False,
                "file_upload_reason": "Private storage and a production malware scanner are not configured.",
                "sarvam_sync": False, "sarvam_sync_reason": "Zero-touch protection is active."}

    @r.get("/knowledge/libraries")
    def libraries(ctx: OrgContext = Depends(org_access("knowledge.view")), db: Session = Depends(get_db)):
        rows = db.scalars(select(KnowledgeLibrary).where(KnowledgeLibrary.organization_id == ctx.org.id)
                          .order_by(func.lower(KnowledgeLibrary.name))).all()
        return [library_out(x) for x in rows]

    @r.post("/knowledge/libraries", status_code=201)
    def create_library(body: LibraryIn, request: Request,
                       ctx: OrgContext = Depends(org_access("knowledge.manage")), db: Session = Depends(get_db)):
        name = body.name.strip()
        if db.scalars(select(KnowledgeLibrary).where(KnowledgeLibrary.organization_id == ctx.org.id,
                                                     func.lower(KnowledgeLibrary.name) == name.lower())).first():
            raise HTTPException(status_code=409, detail="A knowledge library with that name already exists.")
        row = KnowledgeLibrary(organization_id=ctx.org.id, name=name, description=body.description.strip(),
                               created_by=ctx.user.id)
        db.add(row); db.flush()
        audit(db, request, "knowledge.library_created", actor=ctx.user, organization_id=ctx.org.id,
              target_type="knowledge_library", target_id=row.id, details={"name": name})
        db.commit()
        return library_out(row)

    @r.get("/knowledge/documents")
    def documents(library_id: str = "", ctx: OrgContext = Depends(org_access("knowledge.view")),
                  db: Session = Depends(get_db)):
        q = select(KnowledgeDocument).where(KnowledgeDocument.organization_id == ctx.org.id)
        if library_id:
            q = q.where(KnowledgeDocument.library_id == library_id)
        rows = db.scalars(q.order_by(KnowledgeDocument.updated_at.desc())).all()
        revisions = {x.id: x for x in db.scalars(select(KnowledgeDocumentRevision).where(
            KnowledgeDocumentRevision.organization_id == ctx.org.id,
            KnowledgeDocumentRevision.id.in_([x.current_revision_id for x in rows if x.current_revision_id])))}
        return [document_out(x, revisions.get(x.current_revision_id)) for x in rows]

    @r.post("/knowledge/manual", status_code=201)
    def create_manual(body: ManualIn, request: Request,
                      ctx: OrgContext = Depends(org_access("knowledge.manage")), db: Session = Depends(get_db)):
        if body.kind not in ("manual", "faq"):
            raise HTTPException(status_code=422, detail="Kind must be manual or faq.")
        library = db.scalars(select(KnowledgeLibrary).where(KnowledgeLibrary.id == body.library_id,
                                                             KnowledgeLibrary.organization_id == ctx.org.id,
                                                             KnowledgeLibrary.status == "active")).first()
        if library is None:
            raise HTTPException(status_code=404, detail="Library not found.")
        content = body.content.strip()
        digest = _hash(content)
        doc = KnowledgeDocument(organization_id=ctx.org.id, library_id=library.id, kind=body.kind,
                                title=body.title.strip(), created_by=ctx.user.id)
        db.add(doc); db.flush()
        rev = KnowledgeDocumentRevision(organization_id=ctx.org.id, document_id=doc.id, revision_no=1,
                                        source_kind=body.kind, source_locale=body.locale,
                                        processing_state="ready", malware_state="not_applicable", sha256=digest,
                                        extracted_text_hash=digest, parser_name="didm-manual",
                                        parser_version="1", created_by=ctx.user.id, ready_at=utcnow())
        db.add(rev); db.flush()
        block = KnowledgeTextBlock(organization_id=ctx.org.id, revision_id=rev.id, ordinal=0,
                                   block_type=body.kind, text=content, text_hash=digest,
                                   extraction_confidence=100, source_metadata={"title": doc.title})
        db.add(block); db.flush()
        for i, text in enumerate(_chunks(content)):
            db.add(KnowledgeChunk(organization_id=ctx.org.id, revision_id=rev.id, block_id=block.id, ordinal=i,
                                  text=text, token_count=len(text.split()), section_path=[doc.title],
                                  content_hash=_hash(text), chunker_name="didm-manual-words",
                                  chunker_version="1", search_terms=" ".join(sorted(_tokens(text)))))
        doc.current_revision_id = rev.id
        audit(db, request, "knowledge.document_created", actor=ctx.user, organization_id=ctx.org.id,
              target_type="knowledge_document", target_id=doc.id,
              details={"kind": body.kind, "revision_id": rev.id, "content_hash": digest})
        db.commit()
        return document_out(doc, rev)

    @r.get("/knowledge/documents/{document_id}/content")
    def content(document_id: str, request: Request,
                ctx: OrgContext = Depends(org_access("knowledge.content.view")), db: Session = Depends(get_db)):
        doc = scoped_get(db, KnowledgeDocument, ctx.org.id, document_id)
        blocks = db.scalars(select(KnowledgeTextBlock).where(
            KnowledgeTextBlock.organization_id == ctx.org.id,
            KnowledgeTextBlock.revision_id == doc.current_revision_id).order_by(KnowledgeTextBlock.ordinal)).all()
        audit(db, request, "knowledge.content_viewed", actor=ctx.user, organization_id=ctx.org.id,
              target_type="knowledge_document", target_id=doc.id)
        db.commit()
        return {"id": doc.id, "title": doc.title, "content": "\n\n".join(x.text for x in blocks)}

    @r.put("/agents/{agent_id}/versions/{version_id}/knowledge-items")
    def attach(agent_id: str, version_id: str, body: AttachIn, request: Request,
               ctx: OrgContext = Depends(org_access("agents.manage")), db: Session = Depends(get_db)):
        _, version = draft(db, ctx, agent_id, version_id)
        ids = list(dict.fromkeys(body.revision_ids))
        revisions = db.scalars(select(KnowledgeDocumentRevision).where(
            KnowledgeDocumentRevision.organization_id == ctx.org.id,
            KnowledgeDocumentRevision.id.in_(ids), KnowledgeDocumentRevision.processing_state == "ready")).all()
        if len(revisions) != len(ids):
            raise HTTPException(status_code=422, detail="Every selected revision must be ready in this organization.")
        db.execute(delete(AgentVersionKnowledgeItem).where(AgentVersionKnowledgeItem.agent_version_id == version.id))
        for i, revision_id in enumerate(ids):
            db.add(AgentVersionKnowledgeItem(organization_id=ctx.org.id, agent_version_id=version.id,
                                             revision_id=revision_id, ordinal=i, created_by=ctx.user.id))
        version.knowledge_snapshot_id = None
        version.validation_report_id = None
        version.release_state = "draft"
        audit(db, request, "agent_version.knowledge_updated", actor=ctx.user, organization_id=ctx.org.id,
              target_type="agent_version", target_id=version.id, details={"revision_ids": ids})
        db.commit()
        return {"revision_ids": ids}

    @r.put("/agents/{agent_id}/versions/{version_id}/behavior")
    def behavior(agent_id: str, version_id: str, body: BehaviorIn, request: Request,
                 ctx: OrgContext = Depends(org_access("agents.manage")), db: Session = Depends(get_db)):
        _, version = draft(db, ctx, agent_id, version_id)
        if body.role not in ROLES:
            raise HTTPException(status_code=422, detail=f"Role must be one of: {', '.join(ROLES)}.")
        if body.default_language not in body.languages:
            raise HTTPException(status_code=422, detail="Default language must be in supported languages.")
        version.behavior_snapshot = body.model_dump()
        version.validation_report_id = None
        version.knowledge_snapshot_id = None
        version.release_state = "draft"
        audit(db, request, "agent_version.behavior_updated", actor=ctx.user, organization_id=ctx.org.id,
              target_type="agent_version", target_id=version.id, details={"role": body.role,
                                                                           "languages": body.languages})
        db.commit()
        return version.behavior_snapshot

    def attached_ids(db, org_id, version_id):
        return list(db.scalars(select(AgentVersionKnowledgeItem.revision_id).where(
            AgentVersionKnowledgeItem.organization_id == org_id,
            AgentVersionKnowledgeItem.agent_version_id == version_id).order_by(AgentVersionKnowledgeItem.ordinal)))

    @r.post("/agents/{agent_id}/versions/{version_id}/knowledge-search")
    def search(agent_id: str, version_id: str, body: SearchIn,
               ctx: OrgContext = Depends(org_access("agents.preview")), db: Session = Depends(get_db)):
        agent = scoped_get(db, Agent, ctx.org.id, agent_id)
        version = db.scalars(select(AgentVersion).where(AgentVersion.id == version_id,
                                                         AgentVersion.agent_id == agent.id,
                                                         AgentVersion.organization_id == ctx.org.id)).first()
        if version is None:
            raise HTTPException(status_code=404, detail="Not found.")
        ids = attached_ids(db, ctx.org.id, version.id)
        if not ids:
            return {"query": body.query, "results": [], "unknown": True}
        terms = _tokens(body.query)
        rows = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.organization_id == ctx.org.id,
                                                       KnowledgeChunk.revision_id.in_(ids))).all()
        ranked = sorted(((len(terms & _tokens(x.text)), x) for x in rows), key=lambda z: (-z[0], z[1].ordinal))
        results = [{"chunk_id": x.id, "revision_id": x.revision_id, "text": x.text,
                    "page_number": x.page_number, "section_path": x.section_path, "score": score}
                   for score, x in ranked[:body.limit] if score > 0]
        return {"query": body.query, "results": results, "unknown": not results}

    @r.post("/agents/{agent_id}/versions/{version_id}/knowledge-validate")
    def validate(agent_id: str, version_id: str, request: Request,
                 ctx: OrgContext = Depends(org_access("agents.manage")), db: Session = Depends(get_db)):
        _, version = draft(db, ctx, agent_id, version_id)
        behavior = version.behavior_snapshot or {}
        findings = []
        if behavior.get("role") not in ROLES:
            findings.append({"code": "role_required", "message": "Choose an explicit agent role."})
        if not behavior.get("instructions"):
            findings.append({"code": "instructions_required", "message": "Add agent instructions."})
        ids = attached_ids(db, ctx.org.id, version.id)
        if not ids:
            findings.append({"code": "knowledge_required", "message": "Attach at least one ready revision."})
        status = "failed" if findings else "passed"
        run = AgentValidationRun(organization_id=ctx.org.id, agent_version_id=version.id,
                                 validator_version="didm-offline-v1", status=status, findings=findings,
                                 started_by=ctx.user.id, completed_at=utcnow())
        db.add(run); db.flush()
        version.validation_report_id = run.id
        version.release_state = "validation_failed" if findings else "ready"
        audit(db, request, "agent_version.knowledge_validated", actor=ctx.user, organization_id=ctx.org.id,
              target_type="agent_version", target_id=version.id,
              details={"validation_id": run.id, "status": status, "finding_codes": [x["code"] for x in findings]})
        db.commit()
        return {"id": run.id, "status": status, "findings": findings}

    @r.post("/agents/{agent_id}/versions/{version_id}/knowledge-snapshot", status_code=201)
    def snapshot(agent_id: str, version_id: str, request: Request,
                 ctx: OrgContext = Depends(org_access("agents.manage")), db: Session = Depends(get_db)):
        agent, version = draft(db, ctx, agent_id, version_id)
        valid = db.get(AgentValidationRun, version.validation_report_id) if version.validation_report_id else None
        if valid is None or valid.status != "passed":
            raise HTTPException(status_code=409, detail="Pass offline validation before preparing a snapshot.")
        ids = attached_ids(db, ctx.org.id, version.id)
        revisions = db.scalars(select(KnowledgeDocumentRevision).where(
            KnowledgeDocumentRevision.organization_id == ctx.org.id,
            KnowledgeDocumentRevision.id.in_(ids), KnowledgeDocumentRevision.processing_state == "ready")).all()
        by_id = {x.id: x for x in revisions}
        if len(by_id) != len(ids):
            raise HTTPException(status_code=409, detail="Attached knowledge changed or is no longer ready.")
        manifest = {"schema": "didm-knowledge-v1", "agent_id": agent.id, "agent_version_id": version.id,
                    "behavior": version.behavior_snapshot or {},
                    "revisions": [{"id": x, "sha256": by_id[x].sha256,
                                   "text_hash": by_id[x].extracted_text_hash} for x in ids]}
        manifest_hash = _hash(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
        existing = db.scalars(select(KnowledgeSnapshot).where(KnowledgeSnapshot.organization_id == ctx.org.id,
                                                               KnowledgeSnapshot.manifest_hash == manifest_hash)).first()
        if existing:
            snap = existing
        else:
            count = db.scalar(select(func.count(KnowledgeChunk.id)).where(
                KnowledgeChunk.organization_id == ctx.org.id, KnowledgeChunk.revision_id.in_(ids))) or 0
            snap = KnowledgeSnapshot(organization_id=ctx.org.id, agent_id=agent.id, agent_version_id=version.id,
                                     manifest=manifest, manifest_hash=manifest_hash,
                                     chunker_version="didm-manual-words-v1", retrieval_policy_version="lexical-v1",
                                     item_count=len(ids), chunk_count=count, created_by=ctx.user.id)
            db.add(snap); db.flush()
            for i, revision_id in enumerate(ids):
                rev = by_id[revision_id]
                db.add(KnowledgeSnapshotItem(organization_id=ctx.org.id, snapshot_id=snap.id,
                                             revision_id=revision_id, ordinal=i, content_hash=rev.sha256 or "",
                                             extracted_text_hash=rev.extracted_text_hash))
        version.knowledge_snapshot_id = snap.id
        version.content_hash = manifest_hash
        version.release_state = "ready"  # Provider sync is intentionally not started.
        audit(db, request, "agent_version.knowledge_snapshot_prepared", actor=ctx.user,
              organization_id=ctx.org.id, target_type="knowledge_snapshot", target_id=snap.id,
              details={"agent_version_id": version.id, "manifest_hash": manifest_hash})
        db.commit()
        return {"id": snap.id, "manifest_hash": manifest_hash, "item_count": snap.item_count,
                "chunk_count": snap.chunk_count, "release_state": version.release_state,
                "provider_sync": "disabled"}

    @r.post("/agents/{agent_id}/versions/{version_id}/provider-sync")
    def provider_sync(agent_id: str, version_id: str,
                      ctx: OrgContext = Depends(org_access("agents.manage")), db: Session = Depends(get_db)):
        draft(db, ctx, agent_id, version_id)
        # No audit mutation is needed for a prohibited operation; importantly, nothing imports/calls Sarvam.
        raise HTTPException(status_code=409, detail="Knowledge provider synchronization is unavailable. "
                                                     "Sarvam zero-touch protection is active.")

    return r
