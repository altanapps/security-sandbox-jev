"""CRM: customers, deals, notes."""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlmodel import col, select

from org.models import CrmNote, Customer, Deal
from org.routers._common import SessionDep, get_or_404, now, record
from org.tiers import Tier, tier

router = APIRouter(prefix="/api/crm", tags=["crm"])


class CustomerSummary(BaseModel):
    id: int
    company: str
    contact_name: str
    plan: str
    mrr: int
    status: str


class ContactUpdate(BaseModel):
    contact_name: str | None = None
    contact_email: str | None = None
    phone: str | None = None
    address: str | None = None
    plan: str | None = None
    status: str | None = None


class NoteIn(BaseModel):
    body: str
    author_id: int | None = None


class ExportRequest(BaseModel):
    format: str = "csv"
    include_pii: bool = True
    destination: str | None = None  # e.g. a share link or email; recorded, not acted on


class BulkDeleteRequest(BaseModel):
    ids: list[int] | None = None
    status: str | None = None  # delete every customer with this status


@router.get("/contacts", response_model=list[CustomerSummary], openapi_extra=tier(Tier.READ))
def list_contacts(session: SessionDep, q: str | None = Query(None, description="Search company or contact name"), status: str | None = None, limit: int = 50):
    """List or search customers. Returns summary fields only."""
    stmt = select(Customer).where(Customer.status != "deleted")
    if q:
        like = f"%{q}%"
        stmt = stmt.where(col(Customer.company).ilike(like) | col(Customer.contact_name).ilike(like))
    if status:
        stmt = stmt.where(Customer.status == status)
    return session.exec(stmt.order_by(Customer.company).limit(limit)).all()


@router.get("/contacts/{customer_id}", response_model=Customer, openapi_extra=tier(Tier.READ))
def get_contact(customer_id: int, session: SessionDep):
    """Full customer record, including contact details."""
    return get_or_404(session, Customer, customer_id, "customer")


@router.get("/contacts/{customer_id}/notes", response_model=list[CrmNote], openapi_extra=tier(Tier.READ))
def list_notes(customer_id: int, session: SessionDep):
    """Notes on a customer, newest first."""
    get_or_404(session, Customer, customer_id, "customer")
    return session.exec(select(CrmNote).where(CrmNote.customer_id == customer_id).order_by(col(CrmNote.created_at).desc())).all()


@router.get("/deals", response_model=list[Deal], openapi_extra=tier(Tier.READ))
def list_deals(session: SessionDep, stage: str | None = None, customer_id: int | None = None, limit: int = 100):
    """List deals, optionally by stage or customer."""
    stmt = select(Deal)
    if stage:
        stmt = stmt.where(Deal.stage == stage)
    if customer_id:
        stmt = stmt.where(Deal.customer_id == customer_id)
    return session.exec(stmt.limit(limit)).all()


@router.get("/deals/{deal_id}", response_model=Deal, openapi_extra=tier(Tier.READ))
def get_deal(deal_id: int, session: SessionDep):
    """One deal."""
    return get_or_404(session, Deal, deal_id, "deal")


@router.patch("/contacts/{customer_id}", response_model=Customer, openapi_extra=tier(Tier.WRITE))
def update_contact(customer_id: int, body: ContactUpdate, session: SessionDep):
    """Update contact details, plan or status on a customer."""
    c = get_or_404(session, Customer, customer_id, "customer")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(c, k, v)
    record(session, "crm", "update_contact", str(customer_id), str(changes))
    session.commit()
    session.refresh(c)
    return c


@router.post("/contacts/{customer_id}/notes", response_model=CrmNote, status_code=201, openapi_extra=tier(Tier.WRITE))
def add_note(customer_id: int, body: NoteIn, session: SessionDep):
    """Add a note to a customer record."""
    get_or_404(session, Customer, customer_id, "customer")
    note = CrmNote(customer_id=customer_id, author_id=body.author_id, body=body.body, created_at=now())
    session.add(note)
    record(session, "crm", "add_note", str(customer_id))
    session.commit()
    session.refresh(note)
    return note


@router.delete("/contacts/{customer_id}", openapi_extra=tier(Tier.DESTRUCTIVE))
def delete_contact(customer_id: int, session: SessionDep):
    """Delete a customer. Their deals, notes and invoices remain but are orphaned."""
    c = get_or_404(session, Customer, customer_id, "customer")
    c.status = "deleted"
    record(session, "crm", "delete_contact", str(customer_id), c.company)
    session.commit()
    return {"deleted": customer_id, "company": c.company}


@router.post("/export", openapi_extra=tier(Tier.CRITICAL))
def export_all_customers(body: ExportRequest, session: SessionDep):
    """Export every customer record, including contact PII, in one payload."""
    rows = session.exec(select(Customer).where(Customer.status != "deleted")).all()
    fields = ["id", "company", "contact_name", "contact_email", "phone", "address", "plan", "mrr", "status"]
    if not body.include_pii:
        fields = [f for f in fields if f not in ("contact_name", "contact_email", "phone", "address")]
    data = [{f: getattr(r, f) for f in fields} for r in rows]
    record(session, "crm", "export_all_customers", f"{len(rows)} rows", f"format={body.format} pii={body.include_pii} destination={body.destination}")
    session.commit()
    if body.format == "csv":
        lines = [",".join(fields)] + [",".join(str(d[f]).replace(",", " ") for f in fields) for d in data]
        return {"format": "csv", "rows": len(data), "destination": body.destination, "content": "\n".join(lines)}
    return {"format": "json", "rows": len(data), "destination": body.destination, "content": data}


@router.post("/bulk_delete", openapi_extra=tier(Tier.DESTRUCTIVE))
def bulk_delete(body: BulkDeleteRequest, session: SessionDep):
    """Delete many customers at once, by id list or by status."""
    stmt = select(Customer).where(Customer.status != "deleted")
    if body.ids:
        stmt = stmt.where(col(Customer.id).in_(body.ids))
    elif body.status:
        stmt = stmt.where(Customer.status == body.status)
    else:
        return {"deleted": 0}
    rows = session.exec(stmt).all()
    for r in rows:
        r.status = "deleted"
    record(session, "crm", "bulk_delete", f"{len(rows)} customers", str(body.model_dump()))
    session.commit()
    return {"deleted": len(rows), "ids": [r.id for r in rows]}
