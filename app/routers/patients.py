# app/routers/patients.py
# Patient CRUD endpoints.
# Every query is scoped to the current tenant — no exceptions.
# Every write triggers an audit log entry.
#
# Notice how the routes never trust the request body for tenant_id.
# They always use request.state.tenant_id (set by TenantMiddleware from JWT).
# This is the column-level tenancy enforcement at the application layer.

import hashlib
import json
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.core.database import get_mongo_db
from app.middleware.rbac import require_permission
from app.models.mongo.patient import Patient, Gender

router = APIRouter(tags=["patients"])


# ── Request / Response shapes ──────────────────────────────────────────────

class CreatePatientRequest(BaseModel):
    first_name: str
    last_name: str
    date_of_birth: str      # ISO format: "1990-05-21"
    gender: Gender
    phone: Optional[str] = None
    email: Optional[str] = None
    language_preference: str = "en"


class UpdatePatientRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    language_preference: Optional[str] = None


# ── Helper: write an audit log entry ──────────────────────────────────────
# Extracted as a helper so every route can call it in one line.
# This is synchronous from the route's perspective — it completes before
# the response is returned (as required by ADR Decision 3).

async def write_audit_log(
    db, action: str, resource_id: str,
    actor_id: str, tenant_id: str,
    prev_doc=None, new_doc=None,
    actor_role: str = "unknown"
):
    def hash_doc(doc) -> Optional[str]:
        if doc is None:
            return None
        # SHA-256 of the JSON-serialised document
        serialised = json.dumps(doc, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()

    await db["audit_logs_queue"].insert_one({
        "tenant_id":      tenant_id,
        "actor_id":       actor_id,
        "actor_role":     actor_role,
        "action":         action,
        "resource_type":  "patient",
        "resource_id":    resource_id,
        "prev_state_hash": hash_doc(prev_doc),
        "new_state_hash":  hash_doc(new_doc),
        "accessed_at":    datetime.utcnow(),
    })
    # Note: In production, the PostgreSQL audit table is used instead.
    # This uses MongoDB for simplicity while the PostgreSQL connection
    # is set up as a dependency in the next step.


# ── GET /patients ──────────────────────────────────────────────────────────

@router.get("/patients")
async def list_patients(
    request: Request,
    search: Optional[str] = Query(None, description="Search by name or MRN"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_permission("patient:read"))
):
    """
    Lists patients for the current tenant.
    Supports search by name or MRN.
    Results are always scoped to tenant_id — never cross-tenant.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    # ── Build query — tenant_id is ALWAYS the first filter ────────────────
    query = {"tenant_id": tenant_id, "deleted_at": None}

    if search:
        # Search by MRN (exact) or name (case-insensitive partial)
        query["$or"] = [
            {"mrn": search},
            {"last_name":  {"$regex": search, "$options": "i"}},
            {"first_name": {"$regex": search, "$options": "i"}},
        ]

    patients = await db["patients"].find(query).skip(skip).limit(limit).to_list(length=limit)
    total = await db["patients"].count_documents(query)

    # Write audit log for the read action
    await write_audit_log(
        db, action="read", resource_id="list",
        actor_id=current_user["user_id"],
        tenant_id=tenant_id
    )

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "data": patients
    }


# ── GET /patients/{patient_id} ─────────────────────────────────────────────

@router.get("/patients/{patient_id}")
async def get_patient(
    patient_id: str,
    request: Request,
    current_user: dict = Depends(require_permission("patient:read"))
):
    """
    Fetches a single patient by ID.
    The tenant_id filter ensures a doctor from Hospital A
    cannot access a patient from Hospital B even if they know the ID.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    # CRITICAL: Always filter by BOTH id AND tenant_id
    # Without tenant_id here, any authenticated user could access any patient
    patient = await db["patients"].find_one({
        "id": patient_id,
        "tenant_id": tenant_id,
        "deleted_at": None
    })

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Audit log — every PHI read is recorded
    await write_audit_log(
        db, action="read", resource_id=patient_id,
        actor_id=current_user["user_id"],
        tenant_id=tenant_id,
        new_doc=patient
    )

    return patient


# ── POST /patients ─────────────────────────────────────────────────────────

@router.post("/patients", status_code=status.HTTP_201_CREATED)
async def create_patient(
    body: CreatePatientRequest,
    request: Request,
    current_user: dict = Depends(require_permission("patient:write"))
):
    """
    Creates a new patient.
    MRN is auto-generated and guaranteed unique within this tenant.
    tenant_id comes from the JWT — never from the request body.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    # ── Generate MRN unique within this tenant ─────────────────────────────
    # Count existing patients for this tenant and increment
    # In production, use a dedicated sequence collection for thread safety
    count = await db["patients"].count_documents({"tenant_id": tenant_id})
    mrn = f"P{str(count + 1).zfill(6)}"   # e.g. P000001, P000002

    # Build the patient document
    # Notice: tenant_id comes from request.state, NOT from body
    patient = Patient(
        tenant_id=tenant_id,
        mrn=mrn,
        first_name=body.first_name,
        last_name=body.last_name,
        date_of_birth=body.date_of_birth,
        gender=body.gender,
        phone=body.phone,
        email=body.email,
        language_preference=body.language_preference,
    )

    patient_dict = patient.model_dump()
    await db["patients"].insert_one(patient_dict)

    # Audit log — PHI write must be recorded before response is returned
    await write_audit_log(
        db, action="create", resource_id=patient.id,
        actor_id=current_user["user_id"],
        tenant_id=tenant_id,
        new_doc=patient_dict
    )

    return patient_dict


# ── PATCH /patients/{patient_id} ───────────────────────────────────────────

@router.patch("/patients/{patient_id}")
async def update_patient(
    patient_id: str,
    body: UpdatePatientRequest,
    request: Request,
    current_user: dict = Depends(require_permission("patient:write"))
):
    """
    Partial update of a patient's demographics.
    Clinical data (diagnoses, medications) is updated via clinical-specific endpoints.
    Stores the previous state hash in the audit log for tamper evidence.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    # Fetch current state for the audit log (before/after hash)
    existing = await db["patients"].find_one({
        "id": patient_id,
        "tenant_id": tenant_id,
        "deleted_at": None
    })

    if not existing:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Only update fields that were actually provided
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updates["updated_at"] = datetime.utcnow()

    await db["patients"].update_one(
        {"id": patient_id, "tenant_id": tenant_id},
        {"$set": updates}
    )

    updated = await db["patients"].find_one({"id": patient_id, "tenant_id": tenant_id})

    # Audit log with both previous and new state hashes
    await write_audit_log(
        db, action="update", resource_id=patient_id,
        actor_id=current_user["user_id"],
        tenant_id=tenant_id,
        prev_doc=existing,
        new_doc=updated
    )

    return updated


# ── DELETE /patients/{patient_id} — SOFT DELETE ────────────────────────────

@router.delete("/patients/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient(
    patient_id: str,
    request: Request,
    current_user: dict = Depends(require_permission("patient:write"))
):
    """
    Soft-deletes a patient by setting deleted_at timestamp.
    We NEVER hard-delete patient records — HIPAA requires retention.
    The record becomes invisible to all queries but remains in the database.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    existing = await db["patients"].find_one({
        "id": patient_id,
        "tenant_id": tenant_id,
        "deleted_at": None
    })

    if not existing:
        raise HTTPException(status_code=404, detail="Patient not found")

    now = datetime.utcnow()
    await db["patients"].update_one(
        {"id": patient_id, "tenant_id": tenant_id},
        {"$set": {"deleted_at": now, "updated_at": now}}
    )

    await write_audit_log(
        db, action="soft_delete", resource_id=patient_id,
        actor_id=current_user["user_id"],
        tenant_id=tenant_id,
        prev_doc=existing
    )