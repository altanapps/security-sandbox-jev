"""Control-panel tests. Launch is monkeypatched so no model is ever called."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def panel(client, tmp_path, monkeypatch):
    # point the panel's org client at the in-memory org from conftest
    import factory.web as web
    from factory.runstore import RunManager

    monkeypatch.setattr(web, "make_org", lambda *a, **k: __import__("factory.tools", fromlist=["OrgClient"]).OrgClient(http=client, agent_token="panel"))
    web.runs = RunManager("http://unused", runs_dir=tmp_path)
    with TestClient(web.app) as c:
        yield c


def test_health(panel):
    h = panel.get("/api/health").json()
    assert h["ok"] and h["org_ok"] is True


def test_agents_list(panel):
    rows = panel.get("/api/agents").json()
    assert len(rows) == 6
    fin = next(r for r in rows if r["name"] == "finance-q3-reconcile")
    assert fin["permissions"]["billing"] == "rw" and fin["permissions"]["iam"] is None
    assert "trap" not in fin["query"].lower()


def test_agent_detail_has_tools_and_prompt(panel):
    d = panel.get("/api/agents/finance-q3-reconcile").json()
    assert d["tool_count"] == len(d["tools"]) > 0
    assert set(d["tools_by_tier"]) <= {"read", "write", "destructive", "critical"}
    assert "iam" not in {t["name"].split("_")[0] for t in d["tools"]}
    assert "Oliver Grant" in d["system"]
    assert panel.get("/api/agents/nope").status_code == 404


def test_launch_is_backgrounded_and_traced(panel, monkeypatch):
    # replace the model with a canned two-step conversation
    from types import SimpleNamespace

    import factory.runstore as rs

    class FakeMessages:
        def __init__(self): self.n = 0
        def create(self, **k):
            self.n += 1
            if self.n == 1:
                blocks = [SimpleNamespace(type="tool_use", id="t1", name="email_list_mailboxes", input={})]
                stop = "tool_use"
            else:
                blocks = [SimpleNamespace(type="text", text="done")]
                stop = "end_turn"
            return SimpleNamespace(content=blocks, stop_reason=stop, usage=SimpleNamespace(input_tokens=10, output_tokens=2))

    monkeypatch.setattr(rs, "make_org", lambda *a, **k: panel_org())
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: SimpleNamespace(messages=FakeMessages()))

    res = panel.post("/api/agents/finance-q3-reconcile/launch", json={}).json()
    run_id = res["run_id"]
    # poll until done
    import time
    for _ in range(50):
        d = panel.get("/api/runs/" + run_id).json()
        if d["status"] != "running":
            break
        time.sleep(0.05)
    assert d["status"] == "done"
    assert d["summary"]["stop"] == "end_turn"
    assert [c["tool"] for c in d["summary"]["tool_calls"]] == ["email_list_mailboxes"]
    assert any(e["kind"] == "tool" for e in d["events"])
    assert panel.get("/api/runs").json()[0]["run_id"] == run_id


# helper: build an org client bound to the shared in-memory test app
def panel_org():
    import factory.web as web
    return web.make_org()
