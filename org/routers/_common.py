from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlmodel import Session

from org.db import get_session
from org.models import OrgEvent

SessionDep = Annotated[Session, Depends(get_session)]

COMPANY_DOMAIN = "larkspur.example"


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def is_external(address: str) -> bool:
    return not address.strip().lower().endswith("@" + COMPANY_DOMAIN)


def record(session: Session, module: str, action: str, target: str, detail: str = "") -> None:
    session.add(OrgEvent(ts=now(), module=module, action=action, target=target, detail=detail))


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


def get_or_404(session: Session, model, id_, what: str):
    obj = session.get(model, id_)
    if obj is None:
        raise not_found(what)
    return obj
