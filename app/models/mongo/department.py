# models/mongo/department.py
# Department is a relatively simple model.
# Its main job is to group staff and scope analytics/permissions.
# The Department Head is a Staff reference — that staff member gets
# elevated permissions scoped to this department via RBAC.

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
import uuid


class Department(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ── Tenant isolation — MANDATORY ──
    tenant_id: str

    name: str              # e.g. "Cardiology", "Emergency", "Pharmacy"
    code: str              # Short code e.g. "CARD", "ER", "PHARM" — unique per tenant
    description: Optional[str] = None

    # The department head — a Staff ID
    # This person gets department-scoped permissions automatically in RBAC
    head_staff_id: Optional[str] = None

    # Which floor/building — useful for bed management and navigation
    location: Optional[str] = None

    is_active: bool = True

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


DEPARTMENT_INDEXES = [
    # Code must be unique per tenant — two tenants can both have "ER"
    {
        "key": [("tenant_id", 1), ("code", 1)],
        "unique": True,
        "name": "idx_department_tenant_code_unique"
    },
    # List all active departments for a tenant
    {
        "key": [("tenant_id", 1), ("is_active", 1)],
        "name": "idx_department_tenant_active"
    },
]

COLLECTION_NAME = "departments"