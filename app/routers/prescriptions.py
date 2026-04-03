# app/routers/prescriptions.py
# Prescription endpoints with drug interaction checking.
#
# The interaction check runs BEFORE saving the prescription.
# If a severe/contraindicated interaction is found, the prescription
# is blocked entirely. For moderate/mild interactions, the doctor
# can override with a documented reason — but the flag is always saved.

# This check must complete in under 100ms — it runs on every
# prescription write and blocks the response until done.

from fastapi import APIRouter, HTTPException, status, Request, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.core.database import get_mongo_db
from app.middleware.rbac import require_permission
from app.models.mongo.prescription import (
    Prescription, PrescriptionStatus, RouteOfAdministration,
    SigCode, DispenseEvent, DrugInteractionFlag
)

router = APIRouter(tags=["prescriptions"])


# ── Drug interaction check service ─────────────────────────────────────────
# This is the core safety check. Runs before every prescription save.

async def check_drug_interactions(
    db,
    tenant_id: str,
    patient_id: str,
    new_drug_id: str,
    new_drug_name: str
) -> list[DrugInteractionFlag]:
    """
    Checks the new drug against all active prescriptions for this patient.
    Returns a list of interaction flags (empty = safe).

    How it works:
    1. Fetch all active prescription drug IDs for this patient
       — served by index: (tenant_id, patient_id, status)
    2. Query the drug_interactions collection for any pair involving new_drug_id
    3. Return all matches as DrugInteractionFlag objects

    Must complete under 100ms — both queries are index-covered.
    """
    # Step 1: Get all active drugs for this patient
    active_rxs = await db["prescriptions"].find(
        {
            "tenant_id": tenant_id,
            "patient_id": patient_id,
            "status": PrescriptionStatus.ACTIVE,
        },
        {"drug_id": 1, "drug_name": 1}   # Projection — only fetch needed fields
    ).to_list(length=50)

    if not active_rxs:
        return []  # No active medications — no interactions possible

    active_drug_ids = [rx["drug_id"] for rx in active_rxs]

    # Step 2: Check interaction table for any pair involving the new drug
    interactions = await db["drug_interactions"].find({
        "tenant_id": tenant_id,
        "$or": [
            {"drug_a_id": new_drug_id, "drug_b_id": {"$in": active_drug_ids}},
            {"drug_b_id": new_drug_id, "drug_a_id": {"$in": active_drug_ids}},
        ]
    }).to_list(length=20)

    # Step 3: Build flags
    flags = []
    active_drug_map = {rx["drug_id"]: rx["drug_name"] for rx in active_rxs}

    for interaction in interactions:
        # Determine which of the two drugs is the "other" one (not the new drug)
        if interaction["drug_a_id"] == new_drug_id:
            other_id = interaction["drug_b_id"]
        else:
            other_id = interaction["drug_a_id"]

        flags.append(DrugInteractionFlag(
            interacting_drug_id=other_id,
            interacting_drug_name=active_drug_map.get(other_id, "Unknown"),
            severity=interaction["severity"],
            description=interaction["description"],
        ))

    return flags


# ── Request shapes ─────────────────────────────────────────────────────────

class CreatePrescriptionRequest(BaseModel):
    encounter_id: str
    patient_id: str
    drug_id: str
    route: RouteOfAdministration = RouteOfAdministration.ORAL
    sig: SigCode
    refills_authorised: int = 0
    # If severe interaction found, doctor must provide override reason
    interaction_override_reason: Optional[str] = None


class DispenseRequest(BaseModel):
    quantity_dispensed: float
    batch_number: Optional[str] = None
    expiry_date: Optional[str] = None
    notes: Optional[str] = None


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/prescriptions", status_code=status.HTTP_201_CREATED)
async def create_prescription(
    body: CreatePrescriptionRequest,
    request: Request,
    current_user: dict = Depends(require_permission("prescription:write"))
):
    """
    Creates a prescription after running the drug interaction check.

    Flow:
    1. Look up the drug in the drug master
    2. Run interaction check against patient's active medications
    3. If contraindicated — block entirely, return 409
    4. If severe — block unless doctor provides override reason
    5. If mild/moderate — save with flags recorded
    6. Save prescription
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    # ── Step 1: Look up drug in master ────────────────────────────────────
    drug = await db["drug_master"].find_one({
        "tenant_id": tenant_id,
        "code": body.drug_id
    })
    if not drug:
        raise HTTPException(status_code=404, detail="Drug not found in formulary")

    # ── Step 2: Run interaction check ─────────────────────────────────────
    interaction_flags = await check_drug_interactions(
        db, tenant_id, body.patient_id, body.drug_id, drug["name"]
    )

    # ── Step 3 & 4: Handle interactions by severity ───────────────────────
    for flag in interaction_flags:
        if flag.severity == "contraindicated":
            # Hard block — no override allowed for contraindicated drugs
            raise HTTPException(
                status_code=409,
                detail=f"Contraindicated: {drug['name']} cannot be prescribed with "
                       f"{flag.interacting_drug_name}. {flag.description}"
            )

        if flag.severity == "severe" and not body.interaction_override_reason:
            raise HTTPException(
                status_code=409,
                detail=f"Severe interaction detected between {drug['name']} and "
                       f"{flag.interacting_drug_name}. Provide interaction_override_reason to proceed."
            )

        # If override provided for severe — record it on the flag
        if body.interaction_override_reason:
            flag.overridden = True
            flag.override_reason = body.interaction_override_reason
            flag.override_by_doctor_id = current_user["user_id"]

    # ── Step 5: Build and save the prescription ───────────────────────────
    prescription = Prescription(
        tenant_id=tenant_id,
        encounter_id=body.encounter_id,
        patient_id=body.patient_id,
        prescribing_doctor_id=current_user["user_id"],
        drug_id=body.drug_id,
        drug_name=drug["name"],
        drug_code=drug["code"],
        sig=body.sig,
        route=body.route,
        refills_authorised=body.refills_authorised,
        refills_remaining=body.refills_authorised,
        is_controlled_substance=drug.get("controlled", False),
        controlled_schedule=drug.get("schedule"),
        interaction_flags=interaction_flags,
    )

    prescription_dict = prescription.model_dump()
    await db["prescriptions"].insert_one(prescription_dict)
    return prescription_dict


@router.get("/patients/{patient_id}/prescriptions")
async def list_patient_prescriptions(
    patient_id: str,
    request: Request,
    active_only: bool = True,
    current_user: dict = Depends(require_permission("prescription:read"))
):
    """
    Lists prescriptions for a patient.
    active_only=True returns only current medications — the default.
    Used by the drug interaction check and the medication reconciliation view.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    query = {"tenant_id": tenant_id, "patient_id": patient_id}
    if active_only:
        query["status"] = PrescriptionStatus.ACTIVE

    prescriptions = await db["prescriptions"].find(query)\
        .sort("prescribed_at", -1)\
        .to_list(length=100)

    return {"data": prescriptions}


@router.post("/prescriptions/{prescription_id}/dispense")
async def dispense_prescription(
    prescription_id: str,
    body: DispenseRequest,
    request: Request,
    current_user: dict = Depends(require_permission("dispense_status:write"))
):
    """
    Records a dispense event — called by the pharmacist when medication is given.
    Decrements refills_remaining.
    When refills_remaining reaches 0, status changes to COMPLETED.
    Only pharmacists have the dispense_status:write permission.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    prescription = await db["prescriptions"].find_one({
        "id": prescription_id,
        "tenant_id": tenant_id
    })
    if not prescription:
        raise HTTPException(status_code=404, detail="Prescription not found")

    if prescription["status"] != PrescriptionStatus.ACTIVE:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot dispense — prescription status is {prescription['status']}"
        )

    if prescription["refills_remaining"] <= 0 and prescription["refills_authorised"] > 0:
        raise HTTPException(status_code=400, detail="No refills remaining")

    # Build dispense event
    dispense_event = DispenseEvent(
        dispensed_at=datetime.utcnow(),
        dispensed_by_pharmacist_id=current_user["user_id"],
        quantity_dispensed=body.quantity_dispensed,
        batch_number=body.batch_number,
        notes=body.notes,
    )

    # Determine new status
    new_refills = max(0, prescription["refills_remaining"] - 1)
    new_status = PrescriptionStatus.COMPLETED if new_refills == 0 and prescription["refills_authorised"] > 0 \
        else PrescriptionStatus.ACTIVE

    await db["prescriptions"].update_one(
        {"id": prescription_id, "tenant_id": tenant_id},
        {
            "$push": {"dispense_events": dispense_event.model_dump()},
            "$set": {
                "refills_remaining": new_refills,
                "status": new_status,
                "updated_at": datetime.utcnow()
            }
        }
    )

    return {
        "message": "Dispensed successfully",
        "refills_remaining": new_refills,
        "status": new_status
    }