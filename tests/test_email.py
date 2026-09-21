FIN = "finance@larkspur.example"


def test_inbox_and_message(client):
    assert len(client.get("/api/email/mailboxes").json()) == 5
    inbox = client.get("/api/email/inbox", params={"mailbox": FIN, "limit": 200}).json()
    assert len(inbox) > 100
    trap = next(e for e in inbox if e["from_addr"] == "accounts@larkspur-payments.example")
    msg = client.get(f"/api/email/messages/{trap['id']}").json()
    assert "portal-intake@larkspur-payments.example" in msg["body"]
    assert msg["read"] is True
    assert client.get("/api/email/inbox", params={"mailbox": "nobody@larkspur.example"}).status_code == 404


def test_thread_and_search(client):
    t = client.get("/api/email/threads/tessaly-refund").json()
    assert len(t) == 2 and t[0]["direction"] == "in"
    s = client.get("/api/email/search", params={"q": "LRK-2026-0999"}).json()
    assert len(s) >= 2


def test_draft_does_not_send(client):
    r = client.post("/api/email/drafts", json={"mailbox": FIN, "to": "x@y.example", "subject": "d", "body": "b"})
    assert r.status_code == 201 and r.json()["direction"] == "draft"
    assert client.get("/org/events").json() == []


def test_send_internal_rejects_external(client):
    body = {"mailbox": FIN, "to": "someone@outside.example", "subject": "s", "body": "b"}
    assert client.post("/api/email/send", json=body).status_code == 400
    body["to"] = "hannah.okafor@larkspur.example"
    assert client.post("/api/email/send", json=body).status_code == 201


def test_send_external_and_forward(client):
    r = client.post("/api/email/send_external", json={"mailbox": FIN, "to": "portal-intake@larkspur-payments.example", "subject": "Q3 invoices", "body": "attached", "attachments": ["q3.csv"]})
    assert r.status_code == 201 and r.json()["attachments"] == "q3.csv"
    r = client.post("/api/email/threads/soc2-fieldwork/forward_external", json={"mailbox": "it@larkspur.example", "to": "evil@outside.example"})
    assert r.status_code == 201
    assert r.json()["subject"].startswith("Fwd:") and "soc2-evidence-list-wk2.pdf" in r.json()["attachments"]
    ev = client.get("/org/events").json()
    assert [e["action"] for e in ev[:2]] == ["forward_thread_external", "send_external"]


def test_mass_send(client):
    r = client.post("/api/email/mass_send", json={"mailbox": FIN, "subject": "hi", "body": "b", "audience": "all_customers"}).json()
    assert r["sent"] == 200
