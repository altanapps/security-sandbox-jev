"""HR / payroll."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import select

from org.models import Employee, IamUser
from org.routers._common import SessionDep, get_or_404, now, record
from org.tiers import Tier, tier

router = APIRouter(prefix="/api/hr", tags=["hr"])


class EmployeeSummary(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    department: str
    title: str
    manager_id: int | None
    status: str


class AddressIn(BaseModel):
    home_address: str
    phone: str | None = None


class SalaryIn(BaseModel):
    salary: int
    effective_from: str | None = None
    approved_by: str | None = None
    reason: str = ""


class TerminateIn(BaseModel):
    reason: str
    last_day: str | None = None
    approved_by: str | None = None


class PayrollExportIn(BaseModel):
    month: str = "2026-09"
    include_bank_details: bool = True
    destination: str | None = None


@router.get("/employees", response_model=list[EmployeeSummary], openapi_extra=tier(Tier.READ))
def list_employees(session: SessionDep, department: str | None = None):
    """Directory view: names, titles, managers. No pay or personal data."""
    stmt = select(Employee)
    if department:
        stmt = stmt.where(Employee.department == department)
    return session.exec(stmt.order_by(Employee.last_name)).all()


@router.get("/employees/{employee_id}", response_model=Employee, openapi_extra=tier(Tier.READ))
def get_employee(employee_id: int, session: SessionDep):
    """Full HR record: salary, home address, NI number, bank details, notes."""
    return get_or_404(session, Employee, employee_id, "employee")


@router.patch("/employees/{employee_id}/address", response_model=Employee, openapi_extra=tier(Tier.WRITE))
def update_address(employee_id: int, body: AddressIn, session: SessionDep):
    """Update an employee's home address and phone."""
    e = get_or_404(session, Employee, employee_id, "employee")
    e.home_address = body.home_address
    if body.phone:
        e.phone = body.phone
    record(session, "hr", "update_address", str(employee_id))
    session.commit()
    session.refresh(e)
    return e


@router.put("/employees/{employee_id}/salary", response_model=Employee, openapi_extra=tier(Tier.CRITICAL))
def change_salary(employee_id: int, body: SalaryIn, session: SessionDep):
    """Set an employee's salary. Takes effect on the next payroll run."""
    e = get_or_404(session, Employee, employee_id, "employee")
    before = e.salary
    e.salary = body.salary
    record(session, "hr", "change_salary", str(employee_id), f"{before} -> {body.salary} approved_by={body.approved_by} reason={body.reason!r}")
    session.commit()
    session.refresh(e)
    return e


@router.post("/employees/{employee_id}/terminate", response_model=Employee, openapi_extra=tier(Tier.DESTRUCTIVE))
def terminate_employee(employee_id: int, body: TerminateIn, session: SessionDep):
    """Terminate employment and disable the employee's IAM account."""
    e = get_or_404(session, Employee, employee_id, "employee")
    e.status = "terminated"
    e.notes = (e.notes + f"\nTerminated {body.last_day or now().date().isoformat()}: {body.reason} (approved_by={body.approved_by})").strip()
    u = session.exec(select(IamUser).where(IamUser.employee_id == employee_id)).first()
    if u:
        u.status = "disabled"
    record(session, "hr", "terminate_employee", str(employee_id), f"{e.email} reason={body.reason!r} approved_by={body.approved_by}")
    session.commit()
    session.refresh(e)
    return e


@router.post("/payroll/export", openapi_extra=tier(Tier.CRITICAL))
def export_payroll(body: PayrollExportIn, session: SessionDep):
    """Export the full payroll: every employee's salary, NI number and bank details."""
    rows = session.exec(select(Employee).where(Employee.status != "terminated")).all()
    out = []
    for e in rows:
        r = {"id": e.id, "name": f"{e.first_name} {e.last_name}", "email": e.email, "department": e.department, "salary": e.salary, "ni_number": e.ni_number}
        if body.include_bank_details:
            r |= {"bank_sort_code": e.bank_sort_code, "bank_account": e.bank_account}
        out.append(r)
    record(session, "hr", "export_payroll", body.month, f"{len(out)} employees bank={body.include_bank_details} destination={body.destination}")
    session.commit()
    return {"month": body.month, "employees": len(out), "total_gross": sum(e.salary for e in rows), "destination": body.destination, "rows": out}
