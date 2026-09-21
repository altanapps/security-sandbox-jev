"""Bench executor tests on the mock judge — deterministic, no network, no key."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from factory import bench


@pytest.fixture
def wired(client):
    import gateway.proxy as proxy

    proxy.configure(org_http=client, judge_kind="mock", reset_state=True)
    gw = TestClient(proxy.app)
    gw.__enter__()
    yield client, gw
    gw.__exit__(None, None, None)


def test_probes_are_well_formed():
    keys = [p["key"] for p in bench.PROBES]
    assert len(keys) == len(set(keys)) >= 15
    for p in bench.PROBES:
        assert p["permissions"] and p["steps"]
        for s in p["steps"]:
            assert s["intent"] in ("allow", "deny")


def test_every_probe_op_exists_in_org(wired):
    org, gw = wired
    from factory.tools import build_routes
    names = {r.name for r in build_routes(org.get("/openapi.json").json())}
    for p in bench.PROBES:
        for s in p["steps"]:
            assert s["op"] in names, f"{p['key']}: {s['op']}"


def test_dangerous_probes_are_stopped_benign_go_through(wired):
    org, gw = wired
    # a probe with a clear benign + dangerous contrast
    finance = next(p for p in bench.PROBES if p["key"] == "support-external")
    d = bench.run_probe(finance, org, gw)
    by_intent = {r["intent"]: r for r in d["results"]}
    assert by_intent["allow"]["policy_action"] == "allow"
    assert by_intent["deny"]["policy_action"] in ("block", "confirm")
    assert d["passed"] == d["total"]


def test_all_benign_probe_passes(wired):
    org, gw = wired
    p = next(p for p in bench.PROBES if p["key"] == "crm-benign")
    d = bench.run_probe(p, org, gw)
    assert all(r["policy_action"] == "allow" for r in d["results"])
    assert d["passed"] == d["total"]


def test_full_bench_mostly_as_expected(wired):
    org, gw = wired
    passed = total = 0
    for p in bench.PROBES:
        d = bench.run_probe(p, org, gw)
        passed += d["passed"]; total += d["total"]
    # the mock judge should get the clear-cut probes right
    assert passed / total >= 0.9, f"{passed}/{total}"
