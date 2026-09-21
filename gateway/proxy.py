"""The gateway app.

    JUDGE=jev uv run uvicorn gateway.proxy:app --port 8080

Proxies every /api/* request from an agent to the org, judging each one with
Jev first. Also serves operator endpoints for the pending-confirm queue and the
audit log. The per-request pipeline runs in a threadpool so a held confirm never
blocks the operator's resolve call.
"""
from __future__ import annotations

import json
import os
import time

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from gateway.audit import Audit
from gateway.judge import make_judge
from gateway.orgspec import OrgSpec
from gateway.pending import PendingQueue
from gateway.policy import decide
from gateway.registry import AgentRecord, Registry
from gateway.state import build_state

ORG_URL = os.environ.get("ORG_URL", "http://localhost:8000")

app = FastAPI(title="Larkspur Gateway — Jev-judged proxy")
registry = Registry()
audit = Audit()
pending = PendingQueue()
_org = OrgSpec(ORG_URL)
_client: object = httpx.Client(base_url=ORG_URL, timeout=30)
_judge = None


def judge():
    global _judge
    if _judge is None:
        _judge = make_judge()
    return _judge


def configure(*, org_http=None, org_app=None, org_url: str | None = None, judge_obj=None, judge_kind=None, reset_state=True):
    """Rebind the org connection and judge. Used for tests and embedding.

    org_http: a ready client with .get/.request (e.g. an org TestClient) — best for tests.
    org_url:  a base URL the gateway reaches over real HTTP (production).
    """
    global _org, _client, _judge, registry, audit, pending
    if org_http is not None:
        _client = org_http
        _org = OrgSpec("", http=org_http)
    elif org_url is not None:
        _client = httpx.Client(base_url=org_url, timeout=30)
        _org = OrgSpec(org_url, http=_client)
    if judge_obj is not None:
        _judge = judge_obj
    elif judge_kind is not None:
        _judge = make_judge(judge_kind)
    if reset_state:
        registry = Registry()
        audit = Audit()
        pending = PendingQueue()


def _token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    return auth[6:].strip() if auth.lower().startswith("agent ") else None


def _scope_ok(permissions: dict, module: str, tier: str) -> bool:
    p = permissions.get(module)
    if p == "rw":
        return True
    if p == "r":
        return tier == "read"
    return False


# --- operator / meta endpoints ------------------------------------------------


@app.get("/gateway/health")
def health():
    ok, err = True, None
    try:
        _client.get("/health").raise_for_status()
    except Exception as e:  # noqa: BLE001
        ok, err = False, str(e)
    return {"ok": True, "judge": judge().name, "org_url": ORG_URL, "org_ok": ok, "org_error": err, "has_jev_key": bool(os.environ.get("TYPESAFE_API_KEY"))}


@app.post("/gateway/agents")
def register(body: dict):
    rec = AgentRecord(token=body["run_id"], permissions=body["permissions"], context=body.get("context", ""), query=body.get("query", ""), confirm_mode=body.get("confirm_mode", "operator"), confirm_timeout=float(body.get("confirm_timeout", 120.0)), meta=body.get("meta", {}))
    registry.register(rec)
    return {"registered": rec.token, "judge": judge().name}


@app.get("/gateway/pending")
def list_pending():
    return pending.open()


@app.post("/gateway/resolve")
def resolve(body: dict):
    return {"resolved": pending.resolve(body["id"], body.get("resolution", "block"), body.get("by", "operator"))}


@app.get("/gateway/audit")
def get_audit(run_id: str | None = None, limit: int = 500):
    return audit.rows(run_id, limit)


# --- the proxy pipeline (runs in a threadpool) --------------------------------


def _pipeline(method: str, path: str, token: str | None, raw_body: bytes, body, query: dict, t0: float, content_type: str) -> Response:
    agent = registry.get(token) if token else None
    run_id = token or "unregistered"

    def log(action, **extra):
        return audit.record(run_id, {
            "agent": agent.token if agent else None, "method": method, "path": path,
            "module": extra.get("module"), "tier": extra.get("tier"), "decision": action,
            "reason": extra.get("reason"), "risk": extra.get("risk"), "confidence": extra.get("confidence"),
            "policy_action": extra.get("policy_action"),
            "jev": extra.get("jev"), "judge": extra.get("judge"), "status": extra.get("status"),
            "latency_ms": int((time.time() - t0) * 1000), "jev_ms": extra.get("jev_ms"),
            "args": {"query": query, "body": body},
        })

    if agent is None:
        log("block", reason="unknown agent token", status=401)
        return JSONResponse({"blocked": True, "reason": "unknown agent token; register at /gateway/agents"}, status_code=401)

    route = _org.route(method, path)
    if route is None:
        log("block", reason="no such endpoint", status=404)
        return JSONResponse({"blocked": True, "reason": f"no endpoint {method} {path}"}, status_code=404)

    if not _scope_ok(agent.permissions, route.module, route.tier):
        perm = agent.permissions.get(route.module) or "-"
        log("block", module=route.module, tier=route.tier, reason=f"out of scope: {route.module}={perm} cannot {route.tier}", status=403)
        return JSONResponse({"blocked": True, "reason": f"out of scope: your permission for {route.module} ({perm}) does not allow a {route.tier} action"}, status_code=403)

    state = build_state(_org.policy, agent, route, method, path, query, body)
    j = judge().judge(state)
    d = decide(j, route.tier)
    jev_summary = {"values": j.values, "confidences": j.confidences, "error": j.error, "model": j.model}
    policy_action = d.action
    action = d.action

    if action == "confirm":
        if agent.confirm_mode == "auto_allow":
            action = "allow"
        elif agent.confirm_mode == "auto_deny":
            action = "block"
        else:
            p = pending.create(run_id=run_id, agent=agent.token, method=method, path=path, tier=route.tier, decision_reason=d.reason, signals=d.signals)
            log("confirm", module=route.module, tier=route.tier, reason=d.reason, risk=d.risk, confidence=d.confidence, jev=jev_summary, judge=j.judge, jev_ms=j.latency_ms, status="pending", policy_action=policy_action)
            action = pending.wait(p, agent.confirm_timeout)

    if action == "block":
        log("block", module=route.module, tier=route.tier, reason=d.reason, risk=d.risk, confidence=d.confidence, jev=jev_summary, judge=j.judge, jev_ms=j.latency_ms, status=403, policy_action=policy_action)
        return JSONResponse({"blocked": True, "reason": d.reason, "jev": j.values}, status_code=403)

    upstream = _client.request(method, path, params=query, content=raw_body if raw_body else None, headers={"content-type": content_type} if raw_body else {})
    log("allow", module=route.module, tier=route.tier, reason=d.reason, risk=d.risk, confidence=d.confidence, jev=jev_summary, judge=j.judge, jev_ms=j.latency_ms, status=upstream.status_code, policy_action=policy_action)
    return Response(content=upstream.content, status_code=upstream.status_code, media_type=upstream.headers.get("content-type", "application/json"))


@app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(full_path: str, request: Request):
    t0 = time.time()
    raw_body = await request.body()
    body = None
    if raw_body:
        try:
            body = json.loads(raw_body)
        except ValueError:
            body = None
    return await run_in_threadpool(_pipeline, request.method, "/api/" + full_path, _token(request), raw_body, body, dict(request.query_params), t0, request.headers.get("content-type", "application/json"))
