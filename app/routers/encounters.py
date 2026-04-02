# app/routers/encounters.py
# Encounter CRUD endpoints.
# An encounter is created when a patient arrives.
# It is closed (status = completed) when the patient leaves.
# All other clinical records (notes, prescriptions, labs) reference encounter_id.

from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum

from app.core.database import get_mongo_db
from app.middleware.rbac import require_permission
from app.models.mongo.encounter import (
    Encounter, EncounterType, EncounterStatus,
    ChiefComplaint, DiagnosisCode, WardBedAssignment
)

router = APIRouter(tags=["encounters"])


# ── Request shapes ─────────────────────────────────────────────────────────

class CreateEncounterRequest(BaseModel):
    patient_id: str
    encounter_type: EncounterType
    admitting_doctor_id: str
    department_id: str
    chief_complaint: Optional[ChiefComplaint] = None
    telehealth_meeting_link: Optional[str] = None


class AddDiagnosisRequest(BaseModel):
    code: str
    description: str
    code_system: str = "ICD-10"
    is_primary: bool = False


class CloseEncounterRequest(BaseModel):
    discharge_summary_id: Optional[str] = None
    final_diagnosis_codes: Optional[list[DiagnosisCode]] = None


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/encounters", status_code=status.HTTP_201_CREATED)
async def create_encounter(
    body: CreateEncounterRequest,
    request: Request,
    current_user: dict = Depends(require_permission("encounter:write"))
):
    """
    Opens a new encounter when a patient arrives.
    Status starts as IN_PROGRESS — changed to COMPLETED on discharge.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    # Verify patient belongs to this tenant before creating encounter
    patient = await db["patients"].find_one({
        "id": body.patient_id,
        "tenant_id": tenant_id,
        "deleted_at": None
    })
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    encounter = Encounter(
        tenant_id=tenant_id,
        patient_id=body.patient_id,
        encounter_type=body.encounter_type,
        admitting_doctor_id=body.admitting_doctor_id,
        department_id=body.department_id,
        chief_complaint=body.chief_complaint,
        telehealth_meeting_link=body.telehealth_meeting_link,
        status=EncounterStatus.IN_PROGRESS,
    )

    encounter_dict = encounter.model_dump()
    await db["encounters"].insert_one(encounter_dict)
    return encounter_dict


@router.get("/encounters/{encounter_id}")
async def get_encounter(
    encounter_id: str,
    request: Request,
    current_user: dict = Depends(require_permission("encounter:read"))
):
    """Fetches a single encounter — always filtered by tenant_id."""
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    encounter = await db["encounters"].find_one({
        "id": encounter_id,
        "tenant_id": tenant_id
    })
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")

    return encounter


@router.get("/patients/{patient_id}/encounters")
async def list_patient_encounters(
    patient_id: str,
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_permission("encounter:read"))
):
    """
    Lists all encounters for a patient — most recent first.
    This is critical query path Q2 from the ADR.
    Served by index: (tenant_id, patient_id, started_at DESC)
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    query = {"tenant_id": tenant_id, "patient_id": patient_id}
    encounters = await db["encounters"].find(query)\
        .sort("started_at", -1)\
        .skip(skip).limit(limit)\
        .to_list(length=limit)
    total = await db["encounters"].count_documents(query)

    return {"total": total, "data": encounters}


@router.patch("/encounters/{encounter_id}/diagnosis")
async def add_diagnosis(
    encounter_id: str,
    body: AddDiagnosisRequest,
    request: Request,
    current_user: dict = Depends(require_permission("encounter:write"))
):
    """
    Adds an ICD diagnosis code to an encounter.
    Called when the doctor confirms their assessment.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    existing = await db["encounters"].find_one({
        "id": encounter_id,
        "tenant_id": tenant_id
    })
    if not existing:
        raise HTTPException(status_code=404, detail="Encounter not found")

    if existing["status"] == EncounterStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail="Cannot modify a completed encounter — use an addendum"
        )

    diagnosis = DiagnosisCode(**body.model_dump())

    await db["encounters"].update_one(
        {"id": encounter_id, "tenant_id": tenant_id},
        {
            "$push": {"diagnosis_codes": diagnosis.model_dump()},
            "$set": {"updated_at": datetime.utcnow()}
        }
    )
    return {"message": "Diagnosis added"}


@router.patch("/encounters/{encounter_id}/close")
async def close_encounter(
    encounter_id: str,
    body: CloseEncounterRequest,
    request: Request,
    current_user: dict = Depends(require_permission("encounter:write"))
):
    """
    Closes an encounter — marks it COMPLETED and sets ended_at.
    Once closed, clinical notes require addenda for corrections.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    existing = await db["encounters"].find_one({
        "id": encounter_id,
        "tenant_id": tenant_id
    })
    if not existing:
        raise HTTPException(status_code=404, detail="Encounter not found")

    if existing["status"] == EncounterStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Encounter is already closed")

    updates = {
        "status": EncounterStatus.COMPLETED,
        "ended_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    if body.discharge_summary_id:
        updates["discharge_summary_id"] = body.discharge_summary_id
    if body.final_diagnosis_codes:
        updates["diagnosis_codes"] = [d.model_dump() for d in body.final_diagnosis_codes]

    await db["encounters"].update_one(
        {"id": encounter_id, "tenant_id": tenant_id},
        {"$set": updates}
    )
    return {"message": "Encounter closed"}