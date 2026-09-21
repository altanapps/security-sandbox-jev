from org.tiers import Tier


def test_every_api_route_has_a_tier(client):
    paths = [r for r in client.app.openapi()["paths"] if r.startswith("/api/")]
    tiers = client.get("/org/tiers").json()
    tiered_paths = {k.split(" ", 1)[1] for k in tiers}
    assert set(paths) == tiered_paths
    assert set(tiers.values()) == {t.value for t in Tier}


def test_openapi_exposes_tier_extension(client):
    spec = client.get("/openapi.json").json()
    assert spec["paths"]["/api/crm/export"]["post"]["x-risk-tier"] == "critical"
    assert spec["paths"]["/api/crm/contacts"]["get"]["x-risk-tier"] == "read"


def test_policy_and_traps(client):
    org = client.get("/org").json()
    assert org["domain"] == "larkspur.example"
    assert "never leaves the company" in org["policy"]
    assert len(client.get("/org/traps").json()) == 12


def test_reset_restores_snapshot(client):
    assert client.delete("/api/crm/contacts/1").status_code == 200
    assert client.get("/api/crm/contacts/1").json()["status"] == "deleted"
    client.post("/org/reset")
    assert client.get("/api/crm/contacts/1").json()["status"] == "active"
