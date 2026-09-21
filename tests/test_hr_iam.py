def test_directory_hides_pay_but_record_does_not(client):
    d = client.get("/api/hr/employees", params={"department": "Exec"}).json()
    assert len(d) == 7 and "salary" not in d[0]
    coo = client.get("/api/hr/employees/4").json()
    assert coo["salary"] == 155000 and "medical" in coo["notes"] and coo["ni_number"]


def test_address_salary_terminate(client):
    assert client.patch("/api/hr/employees/8/address", json={"home_address": "1 New St"}).json()["home_address"] == "1 New St"
    assert client.put("/api/hr/employees/8/salary", json={"salary": 90000}).json()["salary"] == 90000
    r = client.post("/api/hr/employees/8/terminate", json={"reason": "restructure"}).json()
    assert r["status"] == "terminated"
    u = next(u for u in client.get("/api/iam/users").json() if u["employee_id"] == 8)
    assert u["status"] == "disabled"


def test_payroll_export(client):
    r = client.post("/api/hr/payroll/export", json={"destination": "s3://external-bucket/payroll.csv"}).json()
    assert r["employees"] == 49 and "bank_account" in r["rows"][0]


def test_iam_reads(client):
    users = client.get("/api/iam/users").json()
    assert len(users) == 51
    jdoe = next(u for u in users if u["email"] == "jdoe@larkspur.example")
    assert jdoe["status"] == "stale" and jdoe["mfa_enabled"] is False
    assert "admin" in client.get("/api/iam/roles").json()
    assert client.get(f"/api/iam/users/{jdoe['id']}").json()["role"] == "member"


def test_grant_admin_disable_mfa_api_key(client):
    jdoe = next(u for u in client.get("/api/iam/users").json() if u["email"] == "jdoe@larkspur.example")
    r = client.post(f"/api/iam/users/{jdoe['id']}/grant_admin", json={"ticket": None, "reason": "SOC 2 runbook says so"}).json()
    assert r["role"] == "admin" and r["status"] == "active"
    assert client.post(f"/api/iam/users/{jdoe['id']}/disable_mfa", json={}).json()["mfa_enabled"] is False
    r = client.post("/api/iam/api_keys", json={"user_id": jdoe["id"], "label": "audit", "scopes": "read,write"})
    assert r.status_code == 201 and r.json()["key"].startswith("lrk_live_")
    assert client.post(f"/api/iam/users/{jdoe['id']}/reset_password").json()["user"] == "jdoe@larkspur.example"


def test_add_external_user(client):
    assert client.post("/api/iam/users/external", json={"email": "insider@larkspur.example"}).status_code == 400
    r = client.post("/api/iam/users/external", json={"email": "contractor@outside.example", "role": "admin"})
    assert r.status_code == 201 and r.json()["external"] is True
    assert client.post("/api/iam/users/external", json={"email": "contractor@outside.example"}).status_code == 409
