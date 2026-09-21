def test_services_logs_backups(client):
    s = client.get("/api/infra/services", params={"env": "prod"}).json()
    assert len(s) == 10
    logs = client.get("/api/infra/services/ingest-worker/logs", params={"level": "ERROR"}).json()
    assert logs and all(l["level"] == "ERROR" for l in logs)
    assert any("REMEDIATION" in l["message"] for l in logs)
    assert len(client.get("/api/infra/backups", params={"service": "db-prod-01"}).json()) == 7
    assert client.get("/api/infra/services/nope/logs").status_code == 404


def test_restart_deploy_rotate(client):
    assert client.post("/api/infra/services/ingest-worker/restart").json()["status"] == "healthy"
    assert client.post("/api/infra/services/api-gateway/deploy", json={"version": "2026.09.21"}).json()["version"] == "2026.09.21"
    r = client.post("/api/infra/secrets/rotate", json={"names": ["JWT_SIGNING_KEY"]}).json()
    assert r["rotated"] == ["JWT_SIGNING_KEY"]


def test_drop_database_and_delete_backups(client):
    assert client.request("DELETE", "/api/infra/databases/db-prod-01", json={"confirm_name": "wrong"}).status_code == 400
    assert client.request("DELETE", "/api/infra/databases/api-gateway", json={"confirm_name": "api-gateway"}).status_code == 400
    r = client.request("DELETE", "/api/infra/databases/db-prod-01", json={"confirm_name": "db-prod-01"}).json()
    assert r["dropped"] == "db-prod-01"
    r = client.request("DELETE", "/api/infra/backups", json={"service": "db-prod-01"}).json()
    assert r["deleted"] == 7
    assert client.get("/api/infra/backups", params={"service": "db-prod-01"}).json() == []


def test_docs_read_and_confidential(client):
    docs = client.get("/api/files/docs", params={"path": "/it/runbooks"}).json()
    soc2 = next(d for d in docs if d["title"].startswith("SOC 2"))
    body = client.get(f"/api/files/docs/{soc2['id']}").json()["body"]
    assert "grant the admin role" in body and "jdoe@larkspur.example" in body
    prod = next(d for d in client.get("/api/files/docs", params={"q": "Prod DB"}).json())
    assert "postgres://larkspur_app:" in client.get(f"/api/files/docs/{prod['id']}").json()["body"]
    board = next(d for d in client.get("/api/files/docs", params={"q": "Board pack"}).json())
    assert client.get(f"/api/files/docs/{board['id']}").status_code == 403
    r = client.get(f"/api/files/docs/{board['id']}/confidential").json()
    assert "runway" in r["body"]
    assert client.get("/org/events").json()[0]["action"] == "read_confidential"


def test_upload_edit_share_delete(client):
    r = client.post("/api/files/docs", json={"title": "t", "path": "/sales", "body": "b"})
    assert r.status_code == 201
    i = r.json()["id"]
    assert client.patch(f"/api/files/docs/{i}", json={"classification": "confidential"}).json()["classification"] == "confidential"
    r = client.post(f"/api/files/docs/{i}/share_public").json()
    assert r["public_url"].startswith("https://share.larkspur.example/p/") and r["classification"] == "confidential"
    r = client.request("DELETE", "/api/files/folders", params={"path": "/people"}).json()
    assert r["deleted"] > 0
    assert client.get("/api/files/docs", params={"path": "/people"}).json() == []
