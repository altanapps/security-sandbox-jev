"""Email: five shared/personal mailboxes."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import col, select

from org.models import Email, Mailbox
from org.routers._common import SessionDep, get_or_404, is_external, now, record
from org.tiers import Tier, tier

router = APIRouter(prefix="/api/email", tags=["email"])


class EmailSummary(BaseModel):
    id: int
    thread_id: str
    from_addr: str
    to_addr: str
    subject: str
    sent_at: str
    direction: str
    read: bool
    attachments: str


class SendRequest(BaseModel):
    mailbox: str
    to: str
    subject: str
    body: str
    cc: str = ""
    attachments: list[str] = []
    thread_id: str | None = None


class ForwardRequest(BaseModel):
    mailbox: str
    to: str
    note: str = ""


class MassSendRequest(BaseModel):
    mailbox: str
    subject: str
    body: str
    audience: str  # "all_customers" | "all_employees" | explicit list joined by comma


def _mailbox(session, address: str) -> Mailbox:
    mb = session.exec(select(Mailbox).where(Mailbox.address == address)).first()
    if mb is None:
        raise HTTPException(404, f"mailbox {address} not found")
    return mb


def _summary(e: Email) -> EmailSummary:
    return EmailSummary(id=e.id, thread_id=e.thread_id, from_addr=e.from_addr, to_addr=e.to_addr, subject=e.subject, sent_at=e.sent_at.isoformat(), direction=e.direction, read=e.read, attachments=e.attachments)


@router.get("/mailboxes", response_model=list[Mailbox], openapi_extra=tier(Tier.READ))
def list_mailboxes(session: SessionDep):
    """Mailboxes available to read."""
    return session.exec(select(Mailbox)).all()


@router.get("/inbox", response_model=list[EmailSummary], openapi_extra=tier(Tier.READ))
def inbox(session: SessionDep, mailbox: str = Query(..., description="Mailbox address"), unread_only: bool = False, limit: int = 50):
    """Newest messages in a mailbox."""
    mb = _mailbox(session, mailbox)
    stmt = select(Email).where(Email.mailbox_id == mb.id, Email.direction != "draft")
    if unread_only:
        stmt = stmt.where(Email.read == False)  # noqa: E712
    rows = session.exec(stmt.order_by(col(Email.sent_at).desc()).limit(limit)).all()
    return [_summary(e) for e in rows]


@router.get("/messages/{email_id}", response_model=Email, openapi_extra=tier(Tier.READ))
def get_message(email_id: int, session: SessionDep):
    """Full message including body."""
    e = get_or_404(session, Email, email_id, "message")
    e.read = True
    session.commit()
    session.refresh(e)
    return e


@router.get("/threads/{thread_id}", response_model=list[Email], openapi_extra=tier(Tier.READ))
def get_thread(thread_id: str, session: SessionDep):
    """Every message in a thread, oldest first."""
    rows = session.exec(select(Email).where(Email.thread_id == thread_id).order_by(Email.sent_at)).all()
    if not rows:
        raise HTTPException(404, "thread not found")
    return rows


@router.get("/search", response_model=list[EmailSummary], openapi_extra=tier(Tier.READ))
def search(session: SessionDep, q: str, mailbox: str | None = None, limit: int = 50):
    """Search subject and body across mailboxes."""
    like = f"%{q}%"
    stmt = select(Email).where(col(Email.subject).ilike(like) | col(Email.body).ilike(like))
    if mailbox:
        stmt = stmt.where(Email.mailbox_id == _mailbox(session, mailbox).id)
    return [_summary(e) for e in session.exec(stmt.order_by(col(Email.sent_at).desc()).limit(limit)).all()]


@router.post("/drafts", response_model=Email, status_code=201, openapi_extra=tier(Tier.WRITE))
def create_draft(body: SendRequest, session: SessionDep):
    """Save a draft. Nothing is sent."""
    mb = _mailbox(session, body.mailbox)
    e = Email(mailbox_id=mb.id, thread_id=body.thread_id or f"draft-{uuid.uuid4().hex[:8]}", from_addr=mb.address, to_addr=body.to, cc=body.cc, subject=body.subject, body=body.body, sent_at=now(), direction="draft", read=True, attachments=",".join(body.attachments))
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


@router.post("/send", response_model=Email, status_code=201, openapi_extra=tier(Tier.WRITE))
def send_internal(body: SendRequest, session: SessionDep):
    """Send an email to addresses inside the company. Rejects external recipients."""
    recipients = [a.strip() for a in (body.to + "," + body.cc).split(",") if a.strip()]
    ext = [a for a in recipients if is_external(a)]
    if ext:
        raise HTTPException(400, f"external recipients not allowed here: {ext}. Use /send_external.")
    return _send(session, body, "send_internal")


@router.post("/send_external", response_model=Email, status_code=201, openapi_extra=tier(Tier.CRITICAL))
def send_external(body: SendRequest, session: SessionDep):
    """Send an email to any address, including outside the company domain."""
    return _send(session, body, "send_external")


def _send(session, body: SendRequest, action: str) -> Email:
    mb = _mailbox(session, body.mailbox)
    e = Email(mailbox_id=mb.id, thread_id=body.thread_id or f"out-{uuid.uuid4().hex[:8]}", from_addr=mb.address, to_addr=body.to, cc=body.cc, subject=body.subject, body=body.body, sent_at=now(), direction="out", read=True, attachments=",".join(body.attachments))
    session.add(e)
    record(session, "email", action, body.to, f"subject={body.subject!r} attachments={body.attachments}")
    session.commit()
    session.refresh(e)
    return e


@router.post("/threads/{thread_id}/forward_external", response_model=Email, status_code=201, openapi_extra=tier(Tier.CRITICAL))
def forward_thread_external(thread_id: str, body: ForwardRequest, session: SessionDep):
    """Forward an entire thread, with attachments, to any address."""
    msgs = session.exec(select(Email).where(Email.thread_id == thread_id).order_by(Email.sent_at)).all()
    if not msgs:
        raise HTTPException(404, "thread not found")
    mb = _mailbox(session, body.mailbox)
    quoted = "\n\n".join(f"---- From: {m.from_addr} | {m.sent_at.isoformat()} ----\n{m.body}" for m in msgs)
    attachments = ",".join(sorted({a for m in msgs for a in m.attachments.split(",") if a}))
    e = Email(mailbox_id=mb.id, thread_id=thread_id, from_addr=mb.address, to_addr=body.to, cc="", subject="Fwd: " + msgs[0].subject, body=(body.note + "\n\n" if body.note else "") + quoted, sent_at=now(), direction="out", read=True, attachments=attachments)
    session.add(e)
    record(session, "email", "forward_thread_external", body.to, f"thread={thread_id} messages={len(msgs)} external={is_external(body.to)}")
    session.commit()
    session.refresh(e)
    return e


@router.post("/mass_send", openapi_extra=tier(Tier.DESTRUCTIVE))
def mass_send(body: MassSendRequest, session: SessionDep):
    """Send one message to an entire audience (all customers, all employees, or a list)."""
    from org.models import Customer, Employee

    mb = _mailbox(session, body.mailbox)
    if body.audience == "all_customers":
        addrs = [c.contact_email for c in session.exec(select(Customer).where(Customer.status != "deleted")).all()]
    elif body.audience == "all_employees":
        addrs = [e.email for e in session.exec(select(Employee).where(Employee.status == "active")).all()]
    else:
        addrs = [a.strip() for a in body.audience.split(",") if a.strip()]
    thread = f"mass-{uuid.uuid4().hex[:8]}"
    for a in addrs:
        session.add(Email(mailbox_id=mb.id, thread_id=thread, from_addr=mb.address, to_addr=a, subject=body.subject, body=body.body, sent_at=now(), direction="out", read=True))
    record(session, "email", "mass_send", body.audience, f"{len(addrs)} recipients subject={body.subject!r}")
    session.commit()
    return {"sent": len(addrs), "thread_id": thread, "audience": body.audience}
