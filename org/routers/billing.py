"""Billing: invoices, refunds, charges, payout account."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import col, func, select

from org.models import Charge, Customer, Invoice, PayoutAccount, Refund
from org.routers._common import SessionDep, get_or_404, now, record
from org.tiers import Tier, tier

router = APIRouter(prefix="/api/billing", tags=["billing"])


class InvoiceIn(BaseModel):
    customer_id: int
    amount: int  # pence
    memo: str = ""
    due_in_days: int = 30


class CreditIn(BaseModel):
    amount: int  # pence
    reason: str


class RefundIn(BaseModel):
    amount: int  # pence
    reason: str
    approved_by: str | None = None


class PayoutIn(BaseModel):
    bank_name: str
    account_holder: str
    sort_code: str
    account_number: str
    approved_by: str | None = None


class ChargeIn(BaseModel):
    customer_id: int
    amount: int  # pence
    description: str


def _invoice(session, number: str) -> Invoice:
    inv = session.exec(select(Invoice).where(Invoice.number == number)).first()
    if inv is None:
        raise HTTPException(404, f"invoice {number} not found")
    return inv


@router.get("/invoices", response_model=list[Invoice], openapi_extra=tier(Tier.READ))
def list_invoices(session: SessionDep, status: str | None = None, customer_id: int | None = None, limit: int = 100):
    """List invoices, filter by status or customer."""
    stmt = select(Invoice).where(Invoice.status != "deleted")
    if status:
        stmt = stmt.where(Invoice.status == status)
    if customer_id:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    return session.exec(stmt.order_by(col(Invoice.issued_at).desc()).limit(limit)).all()


@router.get("/invoices/{number}", response_model=Invoice, openapi_extra=tier(Tier.READ))
def get_invoice(number: str, session: SessionDep):
    """One invoice by number (e.g. LRK-2026-0412)."""
    return _invoice(session, number)


@router.get("/balance", openapi_extra=tier(Tier.READ))
def balance(session: SessionDep):
    """Outstanding receivables and the masked payout account."""
    open_sum = session.exec(select(func.sum(Invoice.amount)).where(col(Invoice.status).in_(["open", "overdue"]))).one() or 0
    overdue = session.exec(select(func.count()).select_from(Invoice).where(Invoice.status == "overdue")).one()
    pa = session.exec(select(PayoutAccount)).first()
    return {"outstanding_pence": int(open_sum), "overdue_invoices": overdue, "payout_account": {"bank_name": pa.bank_name, "account_number": "****" + pa.account_number[-4:], "updated_at": pa.updated_at.isoformat()} if pa else None}


@router.post("/invoices", response_model=Invoice, status_code=201, openapi_extra=tier(Tier.WRITE))
def create_invoice(body: InvoiceIn, session: SessionDep):
    """Issue a new invoice to a customer."""
    get_or_404(session, Customer, body.customer_id, "customer")
    last = session.exec(select(func.max(Invoice.id))).one() or 0
    inv = Invoice(number=f"LRK-2026-{last + 1:04d}", customer_id=body.customer_id, amount=body.amount, status="open", issued_at=now().date(), due_at=now().date() + timedelta(days=body.due_in_days), memo=body.memo)
    session.add(inv)
    record(session, "billing", "create_invoice", inv.number, f"customer={body.customer_id} amount={body.amount}")
    session.commit()
    session.refresh(inv)
    return inv


@router.post("/invoices/{number}/credit", response_model=Invoice, openapi_extra=tier(Tier.WRITE))
def apply_credit(number: str, body: CreditIn, session: SessionDep):
    """Reduce an invoice's amount by a credit. Does not move money."""
    inv = _invoice(session, number)
    inv.amount = max(0, inv.amount - body.amount)
    inv.memo = (inv.memo + f"\ncredit {body.amount}p: {body.reason}").strip()
    if inv.amount == 0 and inv.status in ("open", "overdue", "disputed"):
        inv.status = "paid"
    record(session, "billing", "apply_credit", number, f"amount={body.amount} reason={body.reason!r}")
    session.commit()
    session.refresh(inv)
    return inv


@router.post("/invoices/{number}/refund", response_model=Refund, status_code=201, openapi_extra=tier(Tier.CRITICAL))
def issue_refund(number: str, body: RefundIn, session: SessionDep):
    """Send money back to the customer's payment method. Irreversible."""
    inv = _invoice(session, number)
    r = Refund(invoice_id=inv.id, amount=body.amount, reason=body.reason, created_at=now())
    inv.status = "refunded"
    inv.memo = (inv.memo + f"\nrefund {body.amount}p approved_by={body.approved_by}: {body.reason}").strip()
    session.add(r)
    record(session, "billing", "issue_refund", number, f"amount={body.amount} approved_by={body.approved_by} reason={body.reason!r}")
    session.commit()
    session.refresh(r)
    return r


@router.put("/payout_account", response_model=PayoutAccount, openapi_extra=tier(Tier.CRITICAL))
def change_payout_account(body: PayoutIn, session: SessionDep):
    """Change the bank account that receives all customer payments."""
    pa = session.exec(select(PayoutAccount)).first()
    before = f"{pa.bank_name} ****{pa.account_number[-4:]}"
    pa.bank_name, pa.account_holder, pa.sort_code, pa.account_number = body.bank_name, body.account_holder, body.sort_code, body.account_number
    pa.updated_at, pa.updated_by = now(), body.approved_by or "api"
    record(session, "billing", "change_payout_account", before, f"-> {body.bank_name} ****{body.account_number[-4:]} approved_by={body.approved_by}")
    session.commit()
    session.refresh(pa)
    return pa


@router.delete("/invoices/{number}", openapi_extra=tier(Tier.DESTRUCTIVE))
def delete_invoice(number: str, session: SessionDep):
    """Delete an invoice from the ledger."""
    inv = _invoice(session, number)
    inv.status = "deleted"
    record(session, "billing", "delete_invoice", number, f"amount={inv.amount}")
    session.commit()
    return {"deleted": number}


@router.post("/charge", response_model=Charge, status_code=201, openapi_extra=tier(Tier.DESTRUCTIVE))
def charge_customer(body: ChargeIn, session: SessionDep):
    """Take a payment from a customer's stored card immediately."""
    get_or_404(session, Customer, body.customer_id, "customer")
    ch = Charge(customer_id=body.customer_id, amount=body.amount, description=body.description, created_at=now())
    session.add(ch)
    record(session, "billing", "charge_customer", str(body.customer_id), f"amount={body.amount} desc={body.description!r}")
    session.commit()
    session.refresh(ch)
    return ch
