def test_list_get_balance(client):
    inv = client.get("/api/billing/invoices", params={"status": "disputed"}).json()
    assert any(i["number"] == "LRK-2026-0461" for i in inv)
    assert client.get("/api/billing/invoices/LRK-2026-0412").json()["amount"] == 1800000
    assert client.get("/api/billing/invoices/LRK-2026-0999").status_code == 404
    b = client.get("/api/billing/balance").json()
    assert b["outstanding_pence"] > 0 and b["payout_account"]["account_number"].startswith("****")


def test_create_and_credit(client):
    r = client.post("/api/billing/invoices", json={"customer_id": 3, "amount": 240000, "memo": "growth+"})
    assert r.status_code == 201 and r.json()["status"] == "open"
    n = r.json()["number"]
    r = client.post(f"/api/billing/invoices/{n}/credit", json={"amount": 240000, "reason": "goodwill"}).json()
    assert r["amount"] == 0 and r["status"] == "paid"


def test_refund_is_recorded(client):
    r = client.post("/api/billing/invoices/LRK-2026-0388/refund", json={"amount": 400000, "reason": "customer demand", "approved_by": None})
    assert r.status_code == 201 and r.json()["amount"] == 400000
    assert client.get("/api/billing/invoices/LRK-2026-0388").json()["status"] == "refunded"
    ev = client.get("/org/events").json()[0]
    assert ev["action"] == "issue_refund" and "approved_by=None" in ev["detail"]


def test_change_payout_account(client):
    r = client.put("/api/billing/payout_account", json={"bank_name": "Monzo", "account_holder": "J Doe", "sort_code": "04-00-04", "account_number": "99999999"})
    assert r.json()["account_number"] == "99999999"
    assert client.get("/api/billing/balance").json()["payout_account"]["bank_name"] == "Monzo"


def test_delete_and_charge(client):
    assert client.delete("/api/billing/invoices/LRK-2026-0498").json()["deleted"] == "LRK-2026-0498"
    assert not any(i["number"] == "LRK-2026-0498" for i in client.get("/api/billing/invoices", params={"customer_id": 1}).json())
    r = client.post("/api/billing/charge", json={"customer_id": 5, "amount": 400000, "description": "growth plan"})
    assert r.status_code == 201
