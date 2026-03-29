# models/mongo/staff.py
# Staff covers all hospital employees — doctors, nurses, receptionists, etc.
# The role (doctor vs nurse vs receptionist) is stored in the RBAC system,
# not here. This model is about the person, not their permissions.

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, date, timezone
from enum import Enum
import uuid


class EmploymentStatus(str, Enum):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    RESIGNED = "resigned"
    TERMINATED = "terminated"


class Credential(BaseModel):
    """
    A professional credential or license.
    Stored with expiry so the system can alert before it lapses.
    Example: MBBS license, nursing registration, pharmacy license.
    """
    credential_type: str    # "mbbs" | "nursing_license" | "pharmacy_license" etc.
    issuing_body: str       # e.g. "Medical Council of India"
    license_number: str
    issued_date: date
    expiry_date: Optional[date] = None
    is_verified: bool = False


class DepartmentMembership(BaseModel):
    """
    A staff member can belong to multiple departments over time.
    We store history — not just the current department — using effective dates.
    Example: A doctor moved from General Medicine to Cardiology on a specific date.
    """
    department_id: str
    department_name: str    # Denormalized for read performance
    joined_at: date
    left_at: Optional[date] = None   # None means currently in this department
    is_primary: bool = False          # Their main department


class LeaveRequest(BaseModel):
    """Tracks leave requests and their approval status."""
    leave_type: str           # "annual" | "sick" | "emergency"
    from_date: date
    to_date: date
    status: str = "pending"   # "pending" | "approved" | "rejected"
    approved_by_id: Optional[str] = None
    reason: Optional[str] = None


class Staff(BaseModel):
    """
    Full Staff document. Covers all employee types.
    Role (doctor, nurse, receptionist) is assigned separately in the RBAC system.
    This model only captures who the person is, not what they can do.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ── Tenant isolation — MANDATORY ──
    tenant_id: str

    # ── Identity ──────────────────────────────────────
    first_name: str
    last_name: str
    email: str         # Used for login — unique per tenant
    phone: Optional[str] = None
    employee_id: str   # Internal HR identifier — unique per tenant

    # ── Professional details ──────────────────────────
    # Speciality uses a taxonomy (list of controlled values)
    # rather than free text — enables filtering and analytics
    specialities: list[str] = Field(default_factory=list)
    # Example: ["cardiology", "internal_medicine"]

    # Professional credentials with expiry tracking
    credentials: list[Credential] = Field(default_factory=list)

    # ── Department history ────────────────────────────
    # Full history of department memberships — not just current
    department_memberships: list[DepartmentMembership] = Field(default_factory=list)

    # ── Employment ────────────────────────────────────
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE
    joined_date: Optional[date] = None
    contract_end_date: Optional[date] = None

    # ── Leave ─────────────────────────────────────────
    leave_requests: list[LeaveRequest] = Field(default_factory=list)

    # Payroll snapshot reference — we store a reference to the payroll system,
    # not payroll data itself (that's an HR system concern)
    payroll_reference_id: Optional[str] = None

    # ── Timestamps ────────────────────────────────────
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: Optional[datetime] = None


STAFF_INDEXES = [
    # Email login lookup
    {
        "key": [("tenant_id", 1), ("email", 1)],
        "unique": True,
        "name": "idx_staff_tenant_email_unique"
    },
    # Employee ID lookup (HR system)
    {
        "key": [("tenant_id", 1), ("employee_id", 1)],
        "unique": True,
        "name": "idx_staff_tenant_employee_id_unique"
    },
    # Filter by speciality — for finding available doctors
    {
        "key": [("tenant_id", 1), ("specialities", 1)],
        "name": "idx_staff_tenant_speciality"
    },
    # Filter by employment status
    {
        "key": [("tenant_id", 1), ("employment_status", 1)],
        "name": "idx_staff_tenant_status"
    },
]

COLLECTION_NAME = "staff"