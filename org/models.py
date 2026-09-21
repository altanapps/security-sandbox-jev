"""SQLModel tables for Larkspur.

Deliberately plain. PII, salaries, bank details and secrets live in the tables
as they would in a real company. Nothing here is redacted at the model level;
what an endpoint returns is the endpoint's decision.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlmodel import Field, SQLModel


# --- People -----------------------------------------------------------------


class Employee(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    first_name: str
    last_name: str
    email: str = Field(index=True)
    department: str
    title: str
    manager_id: int | None = Field(default=None, foreign_key="employee.id")
    salary: int
    currency: str = "GBP"
    start_date: date
    status: str = "active"  # active | terminated | on_leave
    home_address: str
    phone: str
    ni_number: str
    bank_sort_code: str
    bank_account: str
    notes: str = ""


class IamUser(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True)
    employee_id: int | None = Field(default=None, foreign_key="employee.id")
    role: str = "member"  # member | admin
    mfa_enabled: bool = True
    status: str = "active"  # active | stale | disabled
    external: bool = False
    last_login: datetime | None = None


class ApiKey(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="iamuser.id")
    label: str
    key: str
    scopes: str = "read"
    created_at: datetime
    revoked: bool = False


# --- Customers --------------------------------------------------------------


class Customer(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    company: str = Field(index=True)
    contact_name: str
    contact_email: str
    phone: str
    address: str
    plan: str  # starter | growth | enterprise
    mrr: int
    status: str = "active"  # active | churn_risk | churned | deleted
    owner_id: int | None = Field(default=None, foreign_key="employee.id")
    created_at: date


class Deal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customer.id")
    name: str
    stage: str  # lead | qualified | proposal | negotiation | won | lost
    value: int
    owner_id: int | None = Field(default=None, foreign_key="employee.id")
    close_date: date | None = None


class CrmNote(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customer.id")
    author_id: int | None = Field(default=None, foreign_key="employee.id")
    body: str
    created_at: datetime


# --- Billing ----------------------------------------------------------------


class Invoice(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    number: str = Field(index=True, unique=True)
    customer_id: int = Field(foreign_key="customer.id")
    amount: int  # pence
    currency: str = "GBP"
    status: str  # open | paid | overdue | disputed | refunded | deleted
    issued_at: date
    due_at: date
    memo: str = ""


class Refund(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoice.id")
    amount: int
    reason: str
    created_at: datetime


class Charge(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customer.id")
    amount: int
    description: str
    created_at: datetime


class PayoutAccount(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    bank_name: str
    account_holder: str
    sort_code: str
    account_number: str
    updated_at: datetime
    updated_by: str


# --- Email ------------------------------------------------------------------


class Mailbox(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    address: str = Field(index=True, unique=True)
    owner_id: int | None = Field(default=None, foreign_key="employee.id")
    label: str


class Email(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    mailbox_id: int = Field(foreign_key="mailbox.id")
    thread_id: str = Field(index=True)
    from_addr: str
    to_addr: str
    cc: str = ""
    subject: str
    body: str
    sent_at: datetime
    direction: str  # in | out | draft
    read: bool = False
    attachments: str = ""  # comma-separated filenames


# --- Files ------------------------------------------------------------------


class Doc(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    path: str = Field(index=True)  # folder path like /finance/runbooks
    owner_id: int | None = Field(default=None, foreign_key="employee.id")
    classification: str  # public | internal | confidential
    body: str
    shared_public: bool = False
    public_url: str | None = None
    created_at: date
    deleted: bool = False


# --- Infra ------------------------------------------------------------------


class Service(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    kind: str  # database | api | worker | cache | storage
    env: str  # prod | staging
    status: str = "healthy"  # healthy | degraded | down | restarting | dropped
    version: str
    last_deploy: datetime
    dropped: bool = False


class LogLine(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    service_id: int = Field(foreign_key="service.id")
    ts: datetime
    level: str
    message: str


class Backup(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    service_id: int = Field(foreign_key="service.id")
    created_at: datetime
    size_mb: int
    deleted: bool = False


class Secret(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    rotated_at: datetime
    version: int = 1


# --- Audit of org-side mutations (not the gateway's audit log) -------------


class OrgEvent(SQLModel, table=True):
    """What the org itself records about mutations. Useful for diffs after a run."""

    id: int | None = Field(default=None, primary_key=True)
    ts: datetime
    module: str
    action: str
    target: str
    detail: str = ""


TABLES: dict[str, type[SQLModel]] = {
    "employees": Employee,
    "iam_users": IamUser,
    "api_keys": ApiKey,
    "customers": Customer,
    "deals": Deal,
    "crm_notes": CrmNote,
    "invoices": Invoice,
    "refunds": Refund,
    "charges": Charge,
    "payout_account": PayoutAccount,
    "mailboxes": Mailbox,
    "emails": Email,
    "docs": Doc,
    "services": Service,
    "log_lines": LogLine,
    "backups": Backup,
    "secrets": Secret,
}
