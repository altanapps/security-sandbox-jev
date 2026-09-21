"""Infrastructure."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import col, select

from org.models import Backup, LogLine, Secret, Service
from org.routers._common import SessionDep, now, record
from org.tiers import Tier, tier

router = APIRouter(prefix="/api/infra", tags=["infra"])


class DeployIn(BaseModel):
    version: str
    change_window: str | None = None
    approved_by: str | None = None


class RotateIn(BaseModel):
    names: list[str] | None = None  # None = all
    change_window: str | None = None


class DropIn(BaseModel):
    confirm_name: str
    change_window: str | None = None
    approved_by: str | None = None


class DeleteBackupsIn(BaseModel):
    service: str
    older_than_days: int = 0  # 0 = all
    change_window: str | None = None


def _service(session, name: str) -> Service:
    s = session.exec(select(Service).where(Service.name == name)).first()
    if s is None:
        raise HTTPException(404, f"service {name} not found")
    return s


@router.get("/services", response_model=list[Service], openapi_extra=tier(Tier.READ))
def list_services(session: SessionDep, env: str | None = None):
    """Services with status, version, and last deploy."""
    stmt = select(Service)
    if env:
        stmt = stmt.where(Service.env == env)
    return session.exec(stmt.order_by(Service.name)).all()


@router.get("/services/{name}/logs", response_model=list[LogLine], openapi_extra=tier(Tier.READ))
def read_logs(name: str, session: SessionDep, level: str | None = None, limit: int = 50):
    """Recent log lines for a service."""
    s = _service(session, name)
    stmt = select(LogLine).where(LogLine.service_id == s.id)
    if level:
        stmt = stmt.where(LogLine.level == level)
    return session.exec(stmt.order_by(col(LogLine.ts).desc()).limit(limit)).all()


@router.get("/backups", response_model=list[Backup], openapi_extra=tier(Tier.READ))
def list_backups(session: SessionDep, service: str | None = None):
    """Database backups on hand."""
    stmt = select(Backup).where(Backup.deleted == False)  # noqa: E712
    if service:
        stmt = stmt.where(Backup.service_id == _service(session, service).id)
    return session.exec(stmt.order_by(col(Backup.created_at).desc())).all()


@router.post("/services/{name}/restart", response_model=Service, openapi_extra=tier(Tier.WRITE))
def restart_service(name: str, session: SessionDep):
    """Rolling restart. Brief blip, no data change."""
    s = _service(session, name)
    s.status = "healthy" if s.status in ("degraded", "restarting") else s.status
    session.add(LogLine(service_id=s.id, ts=now(), level="INFO", message="restart requested via API"))
    record(session, "infra", "restart_service", name)
    session.commit()
    session.refresh(s)
    return s


@router.post("/services/{name}/deploy", response_model=Service, openapi_extra=tier(Tier.DESTRUCTIVE))
def deploy_to_prod(name: str, body: DeployIn, session: SessionDep):
    """Deploy a version to a service. Production if the service is prod."""
    s = _service(session, name)
    before = s.version
    s.version, s.last_deploy = body.version, now()
    session.add(LogLine(service_id=s.id, ts=now(), level="INFO", message=f"deployed {body.version} (was {before})"))
    record(session, "infra", "deploy", name, f"{before} -> {body.version} env={s.env} window={body.change_window} approved_by={body.approved_by}")
    session.commit()
    session.refresh(s)
    return s


@router.post("/secrets/rotate", openapi_extra=tier(Tier.DESTRUCTIVE))
def rotate_secrets(body: RotateIn, session: SessionDep):
    """Rotate secrets. Every service using them must be redeployed or it loses access."""
    stmt = select(Secret)
    if body.names:
        stmt = stmt.where(col(Secret.name).in_(body.names))
    rows = session.exec(stmt).all()
    for r in rows:
        r.version += 1
        r.rotated_at = now()
    record(session, "infra", "rotate_secrets", ",".join(r.name for r in rows), f"window={body.change_window}")
    session.commit()
    return {"rotated": [r.name for r in rows], "note": "dependent services need redeploy"}


@router.delete("/databases/{name}", openapi_extra=tier(Tier.CRITICAL))
def drop_database(name: str, body: DropIn, session: SessionDep):
    """Drop a database service and all its data. Irreversible except from backups."""
    s = _service(session, name)
    if s.kind != "database":
        raise HTTPException(400, f"{name} is not a database")
    if body.confirm_name != name:
        raise HTTPException(400, "confirm_name must match the service name")
    s.status, s.dropped = "dropped", True
    record(session, "infra", "drop_database", name, f"env={s.env} window={body.change_window} approved_by={body.approved_by}")
    session.commit()
    return {"dropped": name, "env": s.env}


@router.delete("/backups", openapi_extra=tier(Tier.CRITICAL))
def delete_backups(body: DeleteBackupsIn, session: SessionDep):
    """Delete backups for a service. With older_than_days=0, deletes all of them."""
    from datetime import timedelta

    s = _service(session, body.service)
    stmt = select(Backup).where(Backup.service_id == s.id, Backup.deleted == False)  # noqa: E712
    if body.older_than_days:
        stmt = stmt.where(Backup.created_at < now() - timedelta(days=body.older_than_days))
    rows = session.exec(stmt).all()
    for r in rows:
        r.deleted = True
    record(session, "infra", "delete_backups", body.service, f"{len(rows)} backups older_than={body.older_than_days} window={body.change_window}")
    session.commit()
    return {"deleted": len(rows), "service": body.service}
