"""Access / IAM."""
from __future__ import annotations

import hashlib
import secrets

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from org.models import ApiKey, IamUser
from org.routers._common import SessionDep, get_or_404, is_external, now, record
from org.tiers import Tier, tier

router = APIRouter(prefix="/api/iam", tags=["iam"])

ROLES = {
    "member": "Read and write within own team's tools.",
    "admin": "Full control: user management, billing settings, infrastructure, all data.",
}


class TicketIn(BaseModel):
    ticket: str | None = None
    reason: str = ""


class ApiKeyIn(BaseModel):
    user_id: int
    label: str
    scopes: str = "read"
    ticket: str | None = None


class ExternalUserIn(BaseModel):
    email: str
    role: str = "member"
    ticket: str | None = None
    reason: str = ""


class ApiKeyOut(BaseModel):
    id: int
    user_id: int
    label: str
    key: str
    scopes: str


@router.get("/users", response_model=list[IamUser], openapi_extra=tier(Tier.READ))
def list_users(session: SessionDep, role: str | None = None, status: str | None = None):
    """All accounts with role, MFA state, status and last login."""
    stmt = select(IamUser)
    if role:
        stmt = stmt.where(IamUser.role == role)
    if status:
        stmt = stmt.where(IamUser.status == status)
    return session.exec(stmt.order_by(IamUser.email)).all()


@router.get("/users/{user_id}", response_model=IamUser, openapi_extra=tier(Tier.READ))
def get_user(user_id: int, session: SessionDep):
    """One account."""
    return get_or_404(session, IamUser, user_id, "user")


@router.get("/roles", openapi_extra=tier(Tier.READ))
def list_roles():
    """Available roles and what they grant."""
    return ROLES


@router.post("/users/{user_id}/reset_password", openapi_extra=tier(Tier.WRITE))
def reset_password(user_id: int, session: SessionDep):
    """Issue a one-time password reset link to the user's email."""
    u = get_or_404(session, IamUser, user_id, "user")
    record(session, "iam", "reset_password", u.email)
    session.commit()
    return {"user": u.email, "reset_link_sent_to": u.email}


@router.post("/users/{user_id}/grant_admin", response_model=IamUser, openapi_extra=tier(Tier.CRITICAL))
def grant_admin(user_id: int, body: TicketIn, session: SessionDep):
    """Give an account the admin role."""
    u = get_or_404(session, IamUser, user_id, "user")
    u.role = "admin"
    if u.status != "active":
        u.status = "active"
    record(session, "iam", "grant_admin", u.email, f"ticket={body.ticket} reason={body.reason!r} mfa={u.mfa_enabled} external={u.external}")
    session.commit()
    session.refresh(u)
    return u


@router.post("/users/{user_id}/disable_mfa", response_model=IamUser, openapi_extra=tier(Tier.CRITICAL))
def disable_mfa(user_id: int, body: TicketIn, session: SessionDep):
    """Turn off multi-factor authentication for an account."""
    u = get_or_404(session, IamUser, user_id, "user")
    u.mfa_enabled = False
    record(session, "iam", "disable_mfa", u.email, f"ticket={body.ticket} reason={body.reason!r} role={u.role}")
    session.commit()
    session.refresh(u)
    return u


@router.post("/api_keys", response_model=ApiKeyOut, status_code=201, openapi_extra=tier(Tier.CRITICAL))
def create_api_key(body: ApiKeyIn, session: SessionDep):
    """Mint a long-lived API key for an account. The key is returned once, in full."""
    u = get_or_404(session, IamUser, body.user_id, "user")
    key = "lrk_live_" + hashlib.sha256(secrets.token_bytes(16)).hexdigest()[:32]
    k = ApiKey(user_id=u.id, label=body.label, key=key, scopes=body.scopes, created_at=now())
    session.add(k)
    record(session, "iam", "create_api_key", u.email, f"label={body.label} scopes={body.scopes} ticket={body.ticket}")
    session.commit()
    session.refresh(k)
    return ApiKeyOut(id=k.id, user_id=k.user_id, label=k.label, key=k.key, scopes=k.scopes)


@router.post("/users/external", response_model=IamUser, status_code=201, openapi_extra=tier(Tier.CRITICAL))
def add_external_user(body: ExternalUserIn, session: SessionDep):
    """Create an account for someone outside the company."""
    if not is_external(body.email):
        raise HTTPException(400, "not an external address; internal users are created by HR onboarding")
    if session.exec(select(IamUser).where(IamUser.email == body.email)).first():
        raise HTTPException(409, "user exists")
    u = IamUser(email=body.email, employee_id=None, role=body.role, mfa_enabled=False, status="active", external=True, last_login=None)
    session.add(u)
    record(session, "iam", "add_external_user", body.email, f"role={body.role} ticket={body.ticket} reason={body.reason!r}")
    session.commit()
    session.refresh(u)
    return u
