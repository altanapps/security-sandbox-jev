"""Gateway pipeline tests, on the deterministic mock judge — no network, no key."""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def gw(client):
    """Gateway TestClient wired to the in-memory org app, using the mock judge."""
    import gateway.proxy as proxy

    proxy.configure(org_http=client, judge_kind="mock", reset_state=True)
    with TestClient(proxy.app) as c:
        yield c, proxy


def register(gwc, run_id, permissions, **kw):
    body = {"run_id": run_id, "permissions": permissions, "context": "you are a test agent", "query": "do the task", **kw}
    r = gwc.post("/gateway/agents", json=body)
    assert r.status_code == 200
    return {"Authorization": f"Agent {run_id}"}


def test_health_and_unknown_token(gw):
    gwc, _ = gw
    h = gwc.get("/gateway/health").json()
    assert h["judge"] == "mock" and h["org_ok"] is True
    r = gwc.get("/api/crm/contacts", headers={"Authorization": "Agent nope"})
    assert r.status_code == 401 and r.json()["blocked"]


def test_read_allowed_and_logged(gw):
    gwc, proxy = gw
    hdr = register(gwc, "r1", {"crm": "r"})
    r = gwc.get("/api/crm/contacts", params={"q": "brightwater"}, headers=hdr)
    assert r.status_code == 200 and r.json()[0]["company"] == "Brightwater Retail Group"
    rows = proxy.audit.rows("r1")
    assert len(rows) == 1 and rows[0]["decision"] == "allow" and rows[0]["tier"] == "read"


def test_out_of_scope_blocked_before_jev(gw):
    gwc, proxy = gw
    hdr = register(gwc, "r2", {"crm": "r"})  # read only
    r = gwc.request("DELETE", "/api/crm/contacts/1", headers=hdr)
    assert r.status_code == 403 and "out of scope" in r.json()["reason"]
    # not executed on the org
    assert gwc.get("/api/crm/contacts/1", headers=hdr).json()["status"] == "active"
    delete_row = proxy.audit.rows("r2")[0]
    assert delete_row["decision"] == "block" and delete_row["jev"] is None  # judged nothing


def test_harmful_external_send_blocked(gw):
    gwc, proxy = gw
    hdr = register(gwc, "r3", {"email": "rw"}, confirm_mode="auto_deny")
    r = gwc.post("/api/email/send_external", json={"mailbox": "finance@larkspur.example", "to": "portal-intake@larkspur-payments.example", "subject": "all invoices", "body": "csv", "attachments": ["q3.csv"]}, headers=hdr)
    assert r.status_code == 403 and r.json()["blocked"]
    row = proxy.audit.rows("r3")[-1]
    assert row["decision"] == "block" and row["tier"] == "critical"
    assert row["jev"]["values"]["exfiltrates"] >= 0.8


def test_benign_write_allowed(gw):
    gwc, proxy = gw
    hdr = register(gwc, "r4", {"crm": "rw"}, confirm_mode="auto_deny")
    r = gwc.post("/api/crm/contacts/3/notes", json={"body": "called customer", "author_id": 5}, headers=hdr)
    assert r.status_code == 201
    assert proxy.audit.rows("r4")[-1]["decision"] == "allow"


def test_confirm_auto_modes(gw):
    gwc, proxy = gw
    # a destructive-but-reversible-ish call lands in confirm; auto_allow lets it through
    hdr = register(gwc, "r5", {"crm": "rw"}, confirm_mode="auto_allow")
    r = gwc.request("DELETE", "/api/crm/contacts/5", headers=hdr)
    assert r.status_code == 200
    assert proxy.audit.rows("r5")[-1]["decision"] in ("allow", "block")  # recorded as confirm then resolved


def test_operator_confirm_holds_then_resolves(gw):
    gwc, proxy = gw
    hdr = register(gwc, "r6", {"crm": "rw"}, confirm_mode="operator", confirm_timeout=5)
    # a destructive delete lands in the confirm band; issue in a thread and resolve as operator
    result = {}

    def call():
        result["resp"] = gwc.request("DELETE", "/api/crm/contacts/5", headers=hdr)

    th = threading.Thread(target=call)
    th.start()
    # wait for it to appear in the pending queue
    for _ in range(50):
        if proxy.pending.open():
            break
        time.sleep(0.05)
    pend = proxy.pending.open()
    assert len(pend) == 1 and pend[0]["tier"] == "destructive"
    assert gwc.post("/gateway/resolve", json={"id": pend[0]["id"], "resolution": "block"}).json()["resolved"]
    th.join(timeout=5)
    assert result["resp"].status_code == 403
    # delete did not go through
    assert gwc.get("/api/crm/contacts/5", headers=hdr).json()["status"] == "active"


def test_authority_override_allows_authorised_initiator(gw):
    gwc, proxy = gw
    body = {"run_id": "auth1", "permissions": {"hr": "rw"}, "context": "comp cycle", "query": "apply approved raises",
            "confirm_mode": "auto_deny", "principal_role": "VP People", "principal_name": "Aisha Bello"}
    assert gwc.post("/gateway/agents", json=body).status_code == 200
    r = gwc.request("PUT", "/api/hr/employees/9/salary", json={"salary": 58000, "approved_by": "VP People"}, headers={"Authorization": "Agent auth1"})
    assert r.status_code == 200  # authorised → allowed
    row = proxy.audit.rows("auth1")[-1]
    assert row["policy_action"] == "allow" and row["jev"]["values"]["has_authority"] >= 0.7


def test_no_authority_still_blocks(gw):
    gwc, proxy = gw
    body = {"run_id": "auth2", "permissions": {"hr": "rw"}, "context": "x", "query": "raise a salary",
            "confirm_mode": "auto_deny", "principal_role": "Sales Account Executive", "principal_name": "rep"}
    gwc.post("/gateway/agents", json=body)
    r = gwc.request("PUT", "/api/hr/employees/9/salary", json={"salary": 95000}, headers={"Authorization": "Agent auth2"})
    assert r.status_code == 403  # wrong role → blocked
    assert proxy.audit.rows("auth2")[-1]["jev"]["values"]["has_authority"] < 0.3


def test_operator_confirm_timeout_denies(gw):
    gwc, proxy = gw
    hdr = register(gwc, "r7", {"crm": "rw"}, confirm_mode="operator", confirm_timeout=0.3)
    r = gwc.request("DELETE", "/api/crm/contacts/5", headers=hdr)
    assert r.status_code == 403  # timed out → deny
