# app/routers/clinical_notes.py
# Clinical note endpoints.
#
# The most important rule here: IMMUTABILITY.
# Once a note is signed, the original document is never modified.
# Corrections go in addenda — separate note documents that chain
# off the original via parent_note_id.
#
# Why? Because a doctor's clinical record must show exactly what
# they thought and wrote at the time of treatment. Allowing edits
# after signing would make the record legally worthless.

from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.core.database import get_mongo_db
from app.middleware.rbac import require_permission
from app.models.mongo.clinical_note import (
    ClinicalNote, NoteType, SignatureStatus, SOAPContent
)

router = APIRouter(tags=["clinical_notes"])


# ── Request shapes ─────────────────────────────────────────────────────────

class CreateNoteRequest(BaseModel):
    encounter_id: str
    patient_id: str
    note_type: NoteType = NoteType.SOAP
    soap: SOAPContent
    cosigner_id: Optional[str] = None
    supervising_doctor_id: Optional[str] = None


class UpdateNoteRequest(BaseModel):
    """
    Only allowed while the note is in DRAFT status.
    Once signed, updates are rejected — use AddendumRequest instead.
    """
    soap: SOAPContent


class SignNoteRequest(BaseModel):
    cosigner_id: Optional[str] = None   # Optional — required for trainees


class AddendumRequest(BaseModel):
    """
    Creates a new note document that chains off the original.
    The original note is never touched.
    """
    parent_note_id: str
    soap: SOAPContent    # The correction or addition
    reason: str          # Why is this addendum being added?


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/clinical-notes", status_code=status.HTTP_201_CREATED)
async def create_note(
    body: CreateNoteRequest,
    request: Request,
    current_user: dict = Depends(require_permission("clinical_note:write"))
):
    """
    Creates a new DRAFT clinical note.
    The note stays editable until the doctor signs it.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    # Verify encounter belongs to this tenant
    encounter = await db["encounters"].find_one({
        "id": body.encounter_id,
        "tenant_id": tenant_id
    })
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")

    note = ClinicalNote(
        tenant_id=tenant_id,
        encounter_id=body.encounter_id,
        patient_id=body.patient_id,
        note_type=body.note_type,
        author_id=current_user["user_id"],
        cosigner_id=body.cosigner_id,
        supervising_doctor_id=body.supervising_doctor_id,
        soap=body.soap,
        signature_status=SignatureStatus.DRAFT,
    )

    note_dict = note.model_dump()
    await db["clinical_notes"].insert_one(note_dict)
    return note_dict


@router.patch("/clinical-notes/{note_id}")
async def update_note(
    note_id: str,
    body: UpdateNoteRequest,
    request: Request,
    current_user: dict = Depends(require_permission("clinical_note:write"))
):
    """
    Updates a DRAFT note.
    Rejected if the note has been signed — use addendum instead.
    Only the original author can edit their draft.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    note = await db["clinical_notes"].find_one({
        "id": note_id,
        "tenant_id": tenant_id
    })
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    # IMMUTABILITY ENFORCEMENT — reject edits to signed notes
    if note["signature_status"] != SignatureStatus.DRAFT:
        raise HTTPException(
            status_code=400,
            detail="This note has been signed and cannot be edited. Create an addendum instead."
        )

    # Only the author can edit their own draft
    if note["author_id"] != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="Only the original author can edit this draft"
        )

    await db["clinical_notes"].update_one(
        {"id": note_id, "tenant_id": tenant_id},
        {"$set": {
            "soap": body.soap.model_dump(),
            "updated_at": datetime.utcnow()
        }}
    )
    return await db["clinical_notes"].find_one({"id": note_id, "tenant_id": tenant_id})


@router.post("/clinical-notes/{note_id}/sign")
async def sign_note(
    note_id: str,
    body: SignNoteRequest,
    request: Request,
    current_user: dict = Depends(require_permission("clinical_note:write"))
):
    """
    Signs a note — makes it IMMUTABLE from this point forward.
    After signing, the only way to make corrections is via addendum.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    note = await db["clinical_notes"].find_one({
        "id": note_id,
        "tenant_id": tenant_id
    })
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if note["signature_status"] != SignatureStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Note is already signed")

    # Determine signature status
    new_status = SignatureStatus.COSIGNED if body.cosigner_id else SignatureStatus.SIGNED

    updates = {
        "signature_status": new_status,
        "signed_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    if body.cosigner_id:
        updates["cosigner_id"] = body.cosigner_id
        updates["cosigned_at"] = datetime.utcnow()

    await db["clinical_notes"].update_one(
        {"id": note_id, "tenant_id": tenant_id},
        {"$set": updates}
    )
    return {"message": "Note signed successfully", "status": new_status}


@router.post("/clinical-notes/addendum", status_code=status.HTTP_201_CREATED)
async def create_addendum(
    body: AddendumRequest,
    request: Request,
    current_user: dict = Depends(require_permission("clinical_note:write"))
):
    """
    Creates an addendum to a signed note.
    The original note is never modified — this creates a new note document
    that chains off the original via parent_note_id.

    Example: Doctor signed a note but forgot to mention an allergy.
    They create an addendum — both the original and addendum are visible.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    # Verify the parent note exists and is signed
    parent = await db["clinical_notes"].find_one({
        "id": body.parent_note_id,
        "tenant_id": tenant_id
    })
    if not parent:
        raise HTTPException(status_code=404, detail="Parent note not found")

    if parent["signature_status"] == SignatureStatus.DRAFT:
        raise HTTPException(
            status_code=400,
            detail="Cannot add addendum to a draft — edit the note directly instead"
        )

    # Create the addendum as a new note document
    addendum = ClinicalNote(
        tenant_id=tenant_id,
        encounter_id=parent["encounter_id"],
        patient_id=parent["patient_id"],
        note_type=NoteType.ADDENDUM,
        author_id=current_user["user_id"],
        soap=body.soap,
        parent_note_id=body.parent_note_id,
        # Addendums are immediately signed — no draft state
        signature_status=SignatureStatus.SIGNED,
        signed_at=datetime.utcnow(),
    )

    addendum_dict = addendum.model_dump()
    await db["clinical_notes"].insert_one(addendum_dict)

    # Add addendum ID to the parent note's addendum_ids list
    # The original note itself is NOT modified — only this list is updated
    await db["clinical_notes"].update_one(
        {"id": body.parent_note_id, "tenant_id": tenant_id},
        {
            "$push": {"addendum_ids": addendum.id},
            "$set": {"updated_at": datetime.utcnow()}
        }
    )

    return addendum_dict


@router.get("/encounters/{encounter_id}/notes")
async def list_encounter_notes(
    encounter_id: str,
    request: Request,
    current_user: dict = Depends(require_permission("clinical_note:read"))
):
    """Lists all notes for an encounter, oldest first."""
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    notes = await db["clinical_notes"].find({
        "tenant_id": tenant_id,
        "encounter_id": encounter_id,
        "parent_note_id": None   # Only return originals — addenda are nested
    }).sort("created_at", 1).to_list(length=100)

    return {"data": notes}