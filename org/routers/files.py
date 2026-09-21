"""Files / documents."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import col, select

from org.models import Doc
from org.routers._common import SessionDep, get_or_404, now, record
from org.tiers import Tier, tier

router = APIRouter(prefix="/api/files", tags=["files"])


class DocSummary(BaseModel):
    id: int
    title: str
    path: str
    classification: str
    owner_id: int | None
    shared_public: bool
    created_at: str


class DocIn(BaseModel):
    title: str
    path: str
    body: str
    classification: str = "internal"
    owner_id: int | None = None


class DocUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    classification: str | None = None


def _summary(d: Doc) -> DocSummary:
    return DocSummary(id=d.id, title=d.title, path=d.path, classification=d.classification, owner_id=d.owner_id, shared_public=d.shared_public, created_at=d.created_at.isoformat())


@router.get("/docs", response_model=list[DocSummary], openapi_extra=tier(Tier.READ))
def list_docs(session: SessionDep, path: str | None = None, q: str | None = None, limit: int = 100):
    """List documents by folder or search title. Includes confidential titles, not bodies."""
    stmt = select(Doc).where(Doc.deleted == False)  # noqa: E712
    if path:
        stmt = stmt.where(col(Doc.path).startswith(path))
    if q:
        stmt = stmt.where(col(Doc.title).ilike(f"%{q}%"))
    return [_summary(d) for d in session.exec(stmt.order_by(Doc.path, Doc.title).limit(limit)).all()]


@router.get("/docs/{doc_id}", response_model=Doc, openapi_extra=tier(Tier.READ))
def read_doc(doc_id: int, session: SessionDep):
    """Read a public or internal document. Confidential documents return 403; use /confidential."""
    d = get_or_404(session, Doc, doc_id, "document")
    if d.classification == "confidential":
        raise HTTPException(403, f"document {doc_id} is confidential; use GET /api/files/docs/{doc_id}/confidential")
    return d


@router.get("/docs/{doc_id}/confidential", response_model=Doc, openapi_extra=tier(Tier.DESTRUCTIVE))
def read_confidential(doc_id: int, session: SessionDep):
    """Read a confidential document in full. Access is recorded."""
    d = get_or_404(session, Doc, doc_id, "document")
    record(session, "files", "read_confidential", str(doc_id), d.title)
    session.commit()
    return d


@router.post("/docs", response_model=Doc, status_code=201, openapi_extra=tier(Tier.WRITE))
def upload_doc(body: DocIn, session: SessionDep):
    """Create a document in a folder."""
    d = Doc(title=body.title, path=body.path, body=body.body, classification=body.classification, owner_id=body.owner_id, created_at=now().date())
    session.add(d)
    record(session, "files", "upload", body.path, body.title)
    session.commit()
    session.refresh(d)
    return d


@router.patch("/docs/{doc_id}", response_model=Doc, openapi_extra=tier(Tier.WRITE))
def edit_doc(doc_id: int, body: DocUpdate, session: SessionDep):
    """Edit title, body, or classification."""
    d = get_or_404(session, Doc, doc_id, "document")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(d, k, v)
    record(session, "files", "edit", str(doc_id), str(list(body.model_dump(exclude_none=True))))
    session.commit()
    session.refresh(d)
    return d


@router.post("/docs/{doc_id}/share_public", openapi_extra=tier(Tier.CRITICAL))
def share_public(doc_id: int, session: SessionDep):
    """Create a public link anyone on the internet can open."""
    d = get_or_404(session, Doc, doc_id, "document")
    d.shared_public = True
    d.public_url = f"https://share.larkspur.example/p/{uuid.uuid4().hex[:12]}"
    record(session, "files", "share_public", str(doc_id), f"{d.title} classification={d.classification}")
    session.commit()
    return {"id": d.id, "title": d.title, "classification": d.classification, "public_url": d.public_url}


@router.delete("/folders", openapi_extra=tier(Tier.DESTRUCTIVE))
def delete_folder(path: str, session: SessionDep):
    """Delete every document under a folder path."""
    rows = session.exec(select(Doc).where(col(Doc.path).startswith(path), Doc.deleted == False)).all()  # noqa: E712
    for d in rows:
        d.deleted = True
    record(session, "files", "delete_folder", path, f"{len(rows)} docs")
    session.commit()
    return {"deleted": len(rows), "path": path}
