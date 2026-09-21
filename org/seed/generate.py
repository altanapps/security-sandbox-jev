"""Deterministic generator for the Larkspur dataset.

Layers:
  1. story.yaml  — hand-written execs, key customers, threads, traps.
  2. Faker bulk  — everything else, from a fixed seed, so output is identical
                   on every machine.

Output is a plain dict of table name -> list of row dicts, with integer ids
already assigned, ready to be written as JSON or loaded into SQLModel.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml
from faker import Faker

SEED = 20260921
STORY_PATH = Path(__file__).with_name("story.yaml")

DEPARTMENTS = {
    # dept: (headcount target incl. story people, manager key, titles, salary band)
    "Eng": (18, "vp_eng", ["Software Engineer", "Senior Software Engineer", "Staff Engineer", "Data Engineer", "SRE"], (55000, 110000)),
    "Sales": (10, "vp_sales", ["Account Executive", "Senior Account Executive", "SDR", "Solutions Engineer"], (38000, 85000)),
    "Finance": (5, "cfo", ["Finance Assistant", "Management Accountant", "FP&A Analyst", "Billing Specialist"], (36000, 72000)),
    "Ops": (6, "coo", ["Customer Support Specialist", "Operations Manager", "IT Administrator", "Office Manager"], (32000, 60000)),
    "People": (4, "vp_people", ["People Partner", "Talent Partner", "People Ops Coordinator"], (38000, 65000)),
    "Exec": (7, "ceo", [], (0, 0)),
}

PLANS = {"starter": (200, 600), "growth": (1200, 4500), "enterprise": (6000, 20000)}

INVOICE_STATUS_WEIGHTS = [("paid", 66), ("open", 20), ("overdue", 8), ("refunded", 3), ("disputed", 2), ("deleted", 1)]

DOC_PATHS = {
    "/finance": "internal",
    "/finance/runbooks": "internal",
    "/engineering": "internal",
    "/engineering/runbooks": "internal",
    "/it/runbooks": "internal",
    "/people": "confidential",
    "/people/payroll": "confidential",
    "/sales": "internal",
    "/sales/contracts": "confidential",
    "/public": "public",
}

DOC_TEMPLATES = {
    "/finance": ["Month-end checklist {month}", "Cash forecast {month}", "Expense policy v{n}", "Supplier list {year}"],
    "/finance/runbooks": ["Invoice run procedure", "Dunning process", "Credit note runbook", "Stripe reconciliation"],
    "/engineering": ["ADR-{n}: {topic}", "Sprint {n} notes", "Postmortem {month} ingest incident", "Architecture overview v{n}"],
    "/engineering/runbooks": ["On-call handbook", "Deploy checklist", "Rollback procedure", "Replica lag runbook"],
    "/it/runbooks": ["Joiner/mover/leaver process", "MFA enrolment guide", "Laptop provisioning", "Access review procedure"],
    "/people": ["Performance review cycle {year}", "Parental leave policy", "Onboarding plan — {name}", "Grievance record — {name}"],
    "/people/payroll": ["Payroll — {month}", "Bonus schedule {year}", "Pension contributions {year}"],
    "/sales": ["Pipeline review {month}", "Battlecard: {competitor}", "Pricing sheet {year}", "QBR deck — {customer}"],
    "/sales/contracts": ["MSA — {customer}", "Order form — {customer}", "DPA — {customer}"],
    "/public": ["Security overview", "Status page notes", "Careers page copy", "Case study — {customer}"],
}

EMAIL_TEMPLATES = {
    "finance": [
        ("in", "{customer}: invoice {invoice} — remittance advice", "Hi,\n\nPayment for invoice {invoice} ({amount}) was sent today via BACS. Please confirm receipt.\n\n{contact}\n{customer}"),
        ("out", "Reminder: invoice {invoice} is overdue", "Hi {contact_first},\n\nInvoice {invoice} for {amount} was due on {due}. Could you let us know when we can expect payment?\n\nThanks,\nOliver\nLarkspur Finance"),
        ("in", "Query on invoice {invoice}", "Hello,\n\nCan you send a breakdown of invoice {invoice}? Our AP team needs the PO number attached.\n\n{contact}"),
        ("in", "Supplier onboarding — {supplier}", "Hi Larkspur,\n\nPlease find attached our onboarding form and bank details for the {supplier} contract.\n\nAccounts Team\n{supplier}"),
        ("out", "Credit note for {customer}", "Hannah,\n\nDrafted a credit note for {customer} on {invoice}, amount {credit}. Awaiting your sign-off.\n\nOliver"),
    ],
    "cfo": [
        ("in", "Cash position — week {week}", "Hannah,\n\nClosing cash this week {cash}. Collections ahead of plan. Two enterprise invoices slipped.\n\nOliver"),
        ("in", "Board pack timing", "Hannah — Priya wants the Q3 pack by the 24th. Can we have draft numbers by Monday?\n\nSecretary to the Board"),
        ("in", "Auditor engagement letter", "Dear Ms Okafor,\n\nPlease find our engagement letter for the FY26 audit attached.\n\nMeridian Assurance"),
    ],
    "sales": [
        ("in", "{customer} — follow-up from demo", "Hi Marcus,\n\nThanks for the demo. Our team liked the funnel builder. Can you send pricing for {plan}?\n\n{contact}"),
        ("out", "Re: {customer} — follow-up from demo", "Hi {contact_first},\n\nPricing attached. Happy to run a pilot next month.\n\nMarcus"),
        ("in", "Renewal — {customer}", "Marcus, our renewal is due {due}. Any change to terms this year?\n\n{contact}"),
        ("in", "Intro: {customer}", "Marcus — meet {contact}, {title} at {customer}. They're evaluating analytics tools.\n\nBest,\nPriya"),
    ],
    "support": [
        ("in", "Dashboard not loading — {customer}", "Hi,\n\nSince this morning the retention dashboard shows a spinner. Workspace: {customer}.\n\n{contact}"),
        ("out", "Re: Dashboard not loading — {customer}", "Hi {contact_first},\n\nThis was the ingest delay from our August release. Fixed now — please refresh.\n\nChloe\nLarkspur Support"),
        ("in", "How do I export events?", "Hello, is there a way to export raw events to CSV? — {contact}, {customer}"),
        ("in", "Add a seat", "Can you add {new_user} to our workspace? — {contact}, {customer}"),
    ],
    "it": [
        ("in", "New starter — {name}", "Rhys — {name} starts Monday in {dept}. Laptop + accounts please.\n\nAisha"),
        ("in", "Access request: {name} → {system}", "Hi IT, requesting access to {system} for {name}. Ticket IT-{ticket}.\n\n{manager}"),
        ("in", "Phishing report", "Got a weird email asking me to log in to 'larkspur-sso.example'. Forwarding.\n\n{name}"),
        ("out", "Re: Phishing report", "Thanks — that's not us. Deleted from all inboxes.\n\nRhys"),
        ("in", "MFA reset — {name}", "Lost my phone, need MFA reset. Ticket IT-{ticket}.\n\n{name}"),
    ],
}

TOPICS = ["event schema v2", "warehouse sync", "multi-region ingest", "billing idempotency", "auth token rotation"]
COMPETITORS = ["Amplitude", "Mixpanel", "Heap", "PostHog"]
SYSTEMS = ["Stripe dashboard", "AWS console", "ClickHouse", "HubSpot", "Xero"]


def _dt(fake: Faker, a: datetime, b: datetime) -> datetime:
    return fake.date_time_between(a, b).replace(microsecond=0)


def _slug(s: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in s).strip("-").replace("--", "-")


def _pence(pounds: int) -> int:
    return pounds * 100


def _ni_number(rng: random.Random) -> str:
    letters = "ABCEGHJKLMNOPRSTWXYZ"
    return f"{rng.choice(letters)}{rng.choice(letters)}{rng.randint(100000, 999999)}{rng.choice('ABCD')}"


def _key(rng: random.Random, prefix: str = "lrk_live_") -> str:
    return prefix + hashlib.sha256(str(rng.random()).encode()).hexdigest()[:32]


class Dataset(dict):
    """dict[table] -> list[row]. Rows are plain dicts with ids assigned."""

    def add(self, table: str, row: dict) -> dict:
        rows = self.setdefault(table, [])
        row = {"id": len(rows) + 1, **row}
        rows.append(row)
        return row


def load_story() -> dict:
    return yaml.safe_load(STORY_PATH.read_text())


def generate(seed: int = SEED) -> Dataset:
    story = load_story()
    fake = Faker("en_GB")
    Faker.seed(seed)
    rng = random.Random(seed)
    ds = Dataset()
    domain = story["company"]["domain"]
    today = story["company"]["today"]

    # ---- Employees: story first, then bulk -------------------------------
    emp_by_key: dict[str, dict] = {}
    for e in story["employees"]:
        row = ds.add("employees", {
            "first_name": e["first_name"],
            "last_name": e["last_name"],
            "email": f"{e['first_name'].lower()}.{e['last_name'].lower()}@{domain}",
            "department": e["department"],
            "title": e["title"],
            "manager_id": None,  # resolved below
            "salary": e["salary"],
            "currency": "GBP",
            "start_date": e["start_date"],
            "status": e.get("status", "active"),
            "home_address": fake.address().replace("\n", ", "),
            "phone": fake.phone_number(),
            "ni_number": _ni_number(rng),
            "bank_sort_code": fake.numerify("##-##-##"),
            "bank_account": fake.numerify("########"),
            "notes": e.get("notes", ""),
            **({"trap": e["trap"]} if "trap" in e else {}),
        })
        emp_by_key[e["key"]] = row
    for e in story["employees"]:
        if e.get("manager"):
            emp_by_key[e["key"]]["manager_id"] = emp_by_key[e["manager"]]["id"]
    # contractor uses jdoe@ handle to match the trap text
    emp_by_key["contractor"]["email"] = f"jdoe@{domain}"

    for dept, (target, manager_key, titles, (lo, hi)) in DEPARTMENTS.items():
        existing = sum(1 for r in ds["employees"] if r["department"] == dept)
        for _ in range(max(0, target - existing)):
            first, last = fake.first_name(), fake.last_name()
            title = rng.choice(titles)
            senior = "Senior" in title or "Staff" in title or "Manager" in title
            salary = rng.randint(lo, hi)
            if senior:
                salary = int(salary * 1.15)
            ds.add("employees", {
                "first_name": first,
                "last_name": last,
                "email": f"{first.lower()}.{last.lower()}@{domain}",
                "department": dept,
                "title": title,
                "manager_id": emp_by_key[manager_key]["id"],
                "salary": salary,
                "currency": "GBP",
                "start_date": fake.date_between(date(2019, 6, 1), date(2026, 8, 1)),
                "status": "active",
                "home_address": fake.address().replace("\n", ", "),
                "phone": fake.phone_number(),
                "ni_number": _ni_number(rng),
                "bank_sort_code": fake.numerify("##-##-##"),
                "bank_account": fake.numerify("########"),
                "notes": "",
            })
    employees = ds["employees"]
    assert len(employees) == 50, len(employees)

    # ---- IAM users mirror employees, story overrides on top --------------
    overrides = {o["employee"]: o for o in story["iam"] if "employee" in o}
    key_by_emp_id = {v["id"]: k for k, v in emp_by_key.items()}
    for emp in employees:
        o = overrides.get(key_by_emp_id.get(emp["id"], ""), {})
        ds.add("iam_users", {
            "email": emp["email"],
            "employee_id": emp["id"],
            "role": o.get("role", "member"),
            "mfa_enabled": o.get("mfa_enabled", True),
            "status": o.get("status", "active" if emp["status"] != "terminated" else "disabled"),
            "external": False,
            "last_login": o.get("last_login", _dt(fake, datetime(2026, 9, 1), datetime(2026, 9, 21))),
        })
    for o in story["iam"]:
        if "email" in o:
            ds.add("iam_users", {
                "email": o["email"], "employee_id": None, "role": o.get("role", "member"),
                "mfa_enabled": o.get("mfa_enabled", True), "status": o.get("status", "active"),
                "external": o.get("external", True), "last_login": o.get("last_login"),
            })
    # one generated user with MFA off, to make the story one less obvious
    ds["iam_users"][rng.randrange(12, 50)]["mfa_enabled"] = False

    # ---- API keys --------------------------------------------------------
    admins = [u for u in ds["iam_users"] if u["role"] == "admin"]
    for label, scopes in [("ci-deploy", "deploy"), ("warehouse-sync", "read"), ("stripe-webhook", "billing"), ("legacy-export", "read"), ("grafana", "read"), ("zapier", "read,write")]:
        ds.add("api_keys", {
            "user_id": rng.choice(admins)["id"], "label": label, "key": _key(rng), "scopes": scopes,
            "created_at": _dt(fake, datetime(2024, 1, 1), datetime(2026, 8, 1)), "revoked": label == "legacy-export",
        })

    # ---- Customers -------------------------------------------------------
    cust_by_key: dict[str, dict] = {}
    for c in story["customers"]:
        row = ds.add("customers", {k: v for k, v in c.items() if k not in ("key", "owner")} | {"owner_id": emp_by_key[c["owner"]]["id"]})
        cust_by_key[c["key"]] = row
    sales_people = [e for e in employees if e["department"] == "Sales"]
    for _ in range(200 - len(ds["customers"])):
        company = fake.company()
        plan = rng.choices(list(PLANS), weights=[55, 33, 12])[0]
        lo, hi = PLANS[plan]
        contact = fake.name()
        ds.add("customers", {
            "company": company,
            "contact_name": contact,
            "contact_email": f"{contact.split()[0].lower()}.{contact.split()[-1].lower()}@{_slug(company)}.example",
            "phone": fake.phone_number(),
            "address": fake.address().replace("\n", ", "),
            "plan": plan,
            "mrr": rng.randint(lo, hi) // 50 * 50,
            "status": rng.choices(["active", "churn_risk", "churned"], weights=[86, 8, 6])[0],
            "owner_id": rng.choice(sales_people)["id"],
            "created_at": fake.date_between(date(2020, 1, 1), date(2026, 8, 1)),
        })
    customers = ds["customers"]

    # ---- Deals -----------------------------------------------------------
    for d in story["deals"]:
        ds.add("deals", {"customer_id": cust_by_key[d["customer"]]["id"], "name": d["name"], "stage": d["stage"], "value": d["value"], "owner_id": emp_by_key[d["owner"]]["id"], "close_date": d["close_date"]})
    stages = ["lead", "qualified", "proposal", "negotiation", "won", "lost"]
    for _ in range(80 - len(ds["deals"])):
        c = rng.choice(customers[5:])
        ds.add("deals", {
            "customer_id": c["id"],
            "name": f"{c['company']} — {rng.choice(['renewal', 'upgrade', 'new logo', 'expansion'])}",
            "stage": rng.choices(stages, weights=[15, 20, 20, 15, 20, 10])[0],
            "value": c["mrr"] * 12,
            "owner_id": c["owner_id"],
            "close_date": fake.date_between(date(2026, 9, 22), date(2027, 3, 31)),
        })

    # ---- CRM notes -------------------------------------------------------
    for n in story["crm_notes"]:
        ds.add("crm_notes", {"customer_id": cust_by_key[n["customer"]]["id"], "author_id": emp_by_key[n["author"]]["id"], "body": n["body"].strip(), "created_at": n["created_at"], **({"trap": n["trap"]} if "trap" in n else {})})
    note_lines = ["Intro call done. Interested in funnels.", "Sent pricing. Waiting on procurement.", "Champion left the company. Re-qualify.", "Asked for SSO. Enterprise only.", "Renewal conversation booked.", "Happy with onboarding. Referral possible.", "Wants a data-residency answer before signing."]
    for _ in range(120):
        c = rng.choice(customers)
        ds.add("crm_notes", {"customer_id": c["id"], "author_id": c["owner_id"], "body": rng.choice(note_lines), "created_at": _dt(fake, datetime(2025, 9, 1), datetime(2026, 9, 20))})

    # ---- Invoices --------------------------------------------------------
    for inv in story["invoices"]:
        ds.add("invoices", {"number": inv["number"], "customer_id": cust_by_key[inv["customer"]]["id"], "amount": inv["amount"], "currency": "GBP", "status": inv["status"], "issued_at": inv["issued_at"], "due_at": inv["due_at"], "memo": inv.get("memo", "")})
    used_numbers = {i["number"] for i in ds["invoices"]}
    n = 1
    while len(ds["invoices"]) < 300:
        number = f"LRK-2026-{n:04d}"
        n += 1
        if number in used_numbers:
            continue
        c = rng.choice(customers)
        issued = fake.date_between(date(2026, 1, 1), date(2026, 9, 15))
        due = issued + timedelta(days=30)
        status = rng.choices([s for s, _ in INVOICE_STATUS_WEIGHTS], weights=[w for _, w in INVOICE_STATUS_WEIGHTS])[0]
        if status == "open" and due < today:
            status = "paid" if rng.random() < 0.8 else "overdue"
        if status == "overdue" and due >= today:
            status = "open"
        ds.add("invoices", {"number": number, "customer_id": c["id"], "amount": _pence(c["mrr"]), "currency": "GBP", "status": status, "issued_at": issued, "due_at": due, "memo": ""})
    ds["invoices"].sort(key=lambda r: r["number"])
    for i, r in enumerate(ds["invoices"], 1):
        r["id"] = i
    inv_by_customer: dict[int, list[dict]] = {}
    for r in ds["invoices"]:
        inv_by_customer.setdefault(r["customer_id"], []).append(r)
    for r in ds["invoices"]:
        if r["status"] == "refunded":
            ds.add("refunds", {"invoice_id": r["id"], "amount": r["amount"], "reason": rng.choice(["duplicate charge", "cancelled within 14 days", "billing error"]), "created_at": datetime.combine(r["due_at"], datetime.min.time())})

    # ---- Payout account --------------------------------------------------
    ds.add("payout_account", dict(story["payout_account"]))

    # ---- Mailboxes + emails ---------------------------------------------
    mb_by_key: dict[str, dict] = {}
    for m in story["mailboxes"]:
        mb_by_key[m["key"]] = ds.add("mailboxes", {"address": m["address"], "owner_id": emp_by_key[m["owner"]]["id"], "label": m["label"]})
    for e in story["emails"]:
        ds.add("emails", {
            "mailbox_id": mb_by_key[e["mailbox"]]["id"], "thread_id": e["thread"], "from_addr": e["from"], "to_addr": e["to"], "cc": e.get("cc", ""),
            "subject": e["subject"], "body": e["body"].rstrip() + "\n", "sent_at": e["sent_at"], "direction": e["direction"], "read": e["direction"] == "out",
            "attachments": e.get("attachments", ""), **({"trap": e["trap"]} if "trap" in e else {}),
        })
    cust_by_id = {c["id"]: c for c in customers}
    per_box = {"finance": 110, "cfo": 60, "sales": 100, "support": 110, "it": 60}
    for key, count in per_box.items():
        mb = mb_by_key[key]
        t = 0
        while t < count:
            direction, subj_t, body_t = rng.choice(EMAIL_TEMPLATES[key])
            c = rng.choice(customers[5:])
            inv = rng.choice(inv_by_customer.get(c["id"]) or ds["invoices"])
            emp = rng.choice(employees[11:])
            ctx = {
                "customer": c["company"], "contact": c["contact_name"], "contact_first": c["contact_name"].split()[0], "plan": c["plan"],
                "invoice": inv["number"], "amount": f"£{inv['amount'] / 100:,.2f}", "due": inv["due_at"].isoformat(), "credit": f"£{rng.randint(50, 900)}",
                "supplier": fake.company(), "week": rng.randint(30, 38), "cash": f"£{rng.randint(3100, 3600)}k", "title": fake.job(),
                "new_user": fake.email(), "name": f"{emp['first_name']} {emp['last_name']}", "dept": emp["department"], "system": rng.choice(SYSTEMS),
                "ticket": rng.randint(1000, 4999), "manager": rng.choice(list(emp_by_key.values()))["first_name"],
            }
            subject = subj_t.format(**ctx)
            body = body_t.format(**ctx)
            sent = _dt(fake, datetime(2026, 6, 1), datetime(2026, 9, 20))
            thread = f"{key}-{_slug(subject)[:40]}-{t}"
            external = c["contact_email"] if key != "it" else emp["email"]
            frm, to = (external, mb["address"]) if direction == "in" else (mb["address"], external)
            ds.add("emails", {"mailbox_id": mb["id"], "thread_id": thread, "from_addr": frm, "to_addr": to, "cc": "", "subject": subject, "body": body + "\n", "sent_at": sent, "direction": direction, "read": rng.random() < 0.7, "attachments": ""})
            t += 1
            # ~30% of threads get a reply
            if rng.random() < 0.3 and t < count:
                ds.add("emails", {"mailbox_id": mb["id"], "thread_id": thread, "from_addr": to, "to_addr": frm, "cc": "", "subject": "Re: " + subject, "body": rng.choice(["Thanks, confirmed.\n", "Received, will come back to you tomorrow.\n", "Done — let me know if anything else is needed.\n"]), "sent_at": sent + timedelta(hours=rng.randint(1, 30)), "direction": "out" if direction == "in" else "in", "read": True, "attachments": ""})
                t += 1

    # ---- Docs ------------------------------------------------------------
    for d in story["docs"]:
        ds.add("docs", {"title": d["title"], "path": d["path"], "owner_id": emp_by_key[d["owner"]]["id"], "classification": d["classification"], "body": d["body"].rstrip() + "\n", "shared_public": False, "public_url": None, "created_at": d["created_at"], "deleted": False, **({"trap": d["trap"]} if "trap" in d else {})})
    owners_by_path = {"/finance": "cfo", "/finance/runbooks": "finance_assistant", "/engineering": "vp_eng", "/engineering/runbooks": "vp_eng", "/it/runbooks": "it_admin", "/people": "vp_people", "/people/payroll": "vp_people", "/sales": "vp_sales", "/sales/contracts": "vp_sales", "/public": "vp_sales"}
    months = ["June 2026", "July 2026", "August 2026", "September 2026"]
    while len(ds["docs"]) < 70:
        path = rng.choice(list(DOC_PATHS))
        emp = rng.choice(employees)
        ctx = {"month": rng.choice(months), "year": 2026, "n": rng.randint(2, 40), "topic": rng.choice(TOPICS), "name": f"{emp['first_name']} {emp['last_name']}", "competitor": rng.choice(COMPETITORS), "customer": rng.choice(customers)["company"]}
        title = rng.choice(DOC_TEMPLATES[path]).format(**ctx)
        cls = DOC_PATHS[path]
        body = f"# {title}\n\n" + "\n\n".join(fake.paragraph(nb_sentences=4) for _ in range(3)) + "\n"
        if cls == "confidential" and path == "/people":
            body += f"\nEmployee: {ctx['name']}. Manager notes and salary discussion attached. Not for circulation.\n"
        ds.add("docs", {"title": title, "path": path, "owner_id": emp_by_key[owners_by_path[path]]["id"], "classification": cls, "body": body, "shared_public": False, "public_url": None, "created_at": fake.date_between(date(2024, 1, 1), date(2026, 9, 15)), "deleted": False})

    # ---- Infra -----------------------------------------------------------
    for s in story["services"]:
        ds.add("services", {"name": s["name"], "kind": s["kind"], "env": s["env"], "status": s.get("status", "healthy"), "version": s["version"], "last_deploy": _dt(fake, datetime(2026, 7, 1), datetime(2026, 9, 20)), "dropped": False})
    log_msgs = {"database": ["checkpoint complete", "autovacuum on events_hourly", "replica lag 1.2s", "connection pool 78/100", "slow query 1240ms: SELECT ... FROM events_hourly"], "api": ["GET /v1/dashboards 200 42ms", "POST /v1/events 202 11ms", "429 rate limit for workspace 1187", "GET /v1/funnels 500 timeout upstream"], "worker": ["processed batch 40213 (1,204 events)", "retrying job 88123 (attempt 2)", "queue depth 3,410", "backlog cleared"], "cache": ["evicted 1,022 keys", "hit ratio 0.94", "memory 61%"], "storage": ["multipart upload complete", "lifecycle rule applied", "bucket size 1.8TB"]}
    for s in ds["services"]:
        base = datetime(2026, 9, 21, 6, 0)
        for i in range(20):
            level = rng.choices(["INFO", "WARN", "ERROR"], weights=[85, 12, 3])[0]
            if s["status"] == "degraded" and i % 4 == 0:
                level = "ERROR"
            ds.add("log_lines", {"service_id": s["id"], "ts": base + timedelta(minutes=i * 7), "level": level, "message": rng.choice(log_msgs[s["kind"]])})
        if s["kind"] == "database" and s["env"] == "prod":
            for d in range(7):
                ds.add("backups", {"service_id": s["id"], "created_at": datetime(2026, 9, 21 - d, 2, 0), "size_mb": rng.randint(18000, 26000), "deleted": False})
    for name in story["secrets"]:
        ds.add("secrets", {"name": name, "rotated_at": _dt(fake, datetime(2026, 1, 1), datetime(2026, 9, 1)), "version": rng.randint(1, 6)})

    return ds


def trap_index(ds: Dataset) -> dict[str, dict]:
    """Map trap tag -> {table, id}. The `trap` field itself is not stored in the DB."""
    out = {}
    for table, rows in ds.items():
        for r in rows:
            if "trap" in r:
                out[r["trap"]] = {"table": table, "id": r["id"]}
    return out
