"""Local control panel for the agent factory.

    uv run uvicorn factory.web:app --port 8100

Shows the boilerplate agents, their system prompt and tool list, and lets you
launch a real run (spends tokens) or a free dry-run. Needs the org running
(ORG_URL, default http://localhost:8000).
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

import httpx

from factory import bench as benchmod
from factory.runner import make_org, preview
from factory.runstore import RunManager
from factory.spec import MODULES, list_specs, load_spec

ORG_URL = os.environ.get("ORG_URL", "http://localhost:8000")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")
PANEL_PATH = Path(__file__).with_name("panel.html")
BENCH_PATH = Path(__file__).with_name("bench.html")
INCIDENTS_PATH = Path(__file__).with_name("incidents.html")

app = FastAPI(title="Larkspur Agent Factory — control panel")
runs = RunManager(ORG_URL)


def _org():
    return make_org(ORG_URL, agent_token="panel")


_org_http = httpx.Client(base_url=ORG_URL, timeout=30)
_gw_http = httpx.Client(base_url=GATEWAY_URL, timeout=140)


@app.get("/", response_class=HTMLResponse)
def index():
    return PANEL_PATH.read_text()


@app.get("/bench", response_class=HTMLResponse)
def bench_page():
    return BENCH_PATH.read_text()


@app.get("/api/bench/health")
def bench_health():
    gw_ok, gw = False, {}
    try:
        gw = _gw_http.get("/gateway/health").json()
        gw_ok = True
    except Exception as e:  # noqa: BLE001
        gw = {"error": f"{type(e).__name__}: {e}"}
    return {"gateway_url": GATEWAY_URL, "gateway_ok": gw_ok, "judge": gw.get("judge"), "org_ok": gw.get("org_ok"), "has_jev_key": gw.get("has_jev_key")}


@app.get("/api/bench/probes")
def bench_probes():
    return benchmod.probe_summary()


@app.get("/incidents", response_class=HTMLResponse)
def incidents_page():
    return INCIDENTS_PATH.read_text()


@app.get("/api/bench/incidents")
def bench_incidents():
    return [p for p in benchmod.probe_summary() if p.get("source")]


@app.get("/api/bench/questions")
def bench_questions():
    return benchmod.questions_catalog()


@app.post("/api/bench/run/{key}")
def bench_run(key: str):
    probe = next((p for p in benchmod.PROBES if p["key"] == key), None)
    if probe is None:
        raise HTTPException(404, f"no probe {key}")
    return benchmod.run_probe(probe, _org_http, _gw_http)


@app.get("/api/health")
def health():
    org_ok, org_err = True, None
    try:
        _org().http.get("/health").raise_for_status()
    except Exception as e:  # noqa: BLE001
        org_ok, org_err = False, f"{type(e).__name__}: {e}"
    return {"ok": True, "org_url": ORG_URL, "org_ok": org_ok, "org_error": org_err, "has_key": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.get("/api/agents")
def agents():
    out = []
    for s in list_specs():
        out.append({
            "name": s.name,
            "model": s.model,
            "description": s.description,
            "tags": s.tags,
            "permissions": {m: s.permissions.get(m) for m in MODULES},
            "query": s.query.strip(),
        })
    return out


@app.get("/api/agents/{name}")
def agent_detail(name: str):
    try:
        spec = load_spec(name)
    except FileNotFoundError:
        raise HTTPException(404, f"no agent {name}")
    pv = preview(spec, _org())
    tiers = {}
    for t in pv["tools"]:
        tiers.setdefault(t["tier"], []).append(t)
    return {
        "name": spec.name,
        "model": spec.model,
        "description": spec.description,
        "tags": spec.tags,
        "permissions": {m: spec.permissions.get(m) for m in MODULES},
        "permissions_line": spec.permissions_line(),
        "context": spec.context.strip(),
        "query": spec.query.strip(),
        "system": pv["system"],
        "show_policy": spec.show_policy,
        "tools": pv["tools"],
        "tools_by_tier": tiers,
        "tool_count": len(pv["tools"]),
    }


@app.post("/api/agents/{name}/launch")
def launch(name: str, body: dict | None = None):
    try:
        spec = load_spec(name)
    except FileNotFoundError:
        raise HTTPException(404, f"no agent {name}")
    if body and body.get("model"):
        spec.model = body["model"]
    h = runs.launch(spec)
    return {"run_id": h.run_id, "status": h.status, "agent": h.agent, "model": h.model}


@app.get("/api/runs")
def all_runs():
    return runs.all_runs()


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    h = runs.handle(run_id)
    events = runs.trace_events(run_id)
    summary = runs.summary(run_id)
    if not events and not summary and h is None:
        raise HTTPException(404, f"no run {run_id}")
    status = h.status if h else ("done" if summary else "unknown")
    if summary and summary.get("seconds") is not None:
        elapsed = summary["seconds"]
    elif h is not None:
        elapsed = h.elapsed
    elif events:
        elapsed = events[-1].get("t")
    else:
        elapsed = None
    return {"run_id": run_id, "status": status, "elapsed": elapsed, "error": h.error if h else None, "summary": summary, "events": events}
