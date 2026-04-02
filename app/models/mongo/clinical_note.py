# app/models/mongo/clinical_note.py
# Clinical notes are what doctors write during an encounter.
# Two critical design rules:
#
# 1. IMMUTABILITY — once a note is signed, the original cannot be edited.
#    Corrections go in addenda (separate documents chained to the original).
#    This is a HIPAA requirement and a patient safety requirement.
#
# 2. SOAP STRUCTURE — Subjective, Objective, Assessment, Plan.
#    This is the international standard for clinical documentation.
#    It makes notes consistent and searchable across the system.

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum
import uuid


class NoteType(str, Enum):
    SOAP = "soap"                   # Standard doctor note
    NURSING = "nursing"             # Nursing observation note
    DISCHARGE_SUMMARY = "discharge_summary"
    PROCEDURE = "procedure"         # What was done during a procedure
    ADDENDUM = "addendum"           # Correction/addition to an existing note
    REFERRAL = "referral"           # Referral letter to a specialist


class SignatureStatus(str, Enum):
    DRAFT = "draft"           # Being written — can still be edited
    SIGNED = "signed"         # Doctor signed — IMMUTABLE from this point
    COSIGNED = "cosigned"     # Senior doctor co-signed (e.g. for residents)


class SOAPContent(BaseModel):
    """
    The four sections of a SOAP note.
    All are optional individually — a nursing note may only have S and O.
    But at least one must be present (enforced at the route level).

    S — Subjective: What the patient tells you
        "Patient complains of chest pain for 3 days, worse on exertion"

    O — Objective: What you observe and measure
        "BP 140/90, HR 88, SpO2 97%. Mild tenderness on palpation."

    A — Assessment: Your clinical judgment / diagnosis
        "Likely stable angina. Rule out ACS."

    P — Plan: What you're going to do about it
        "ECG, troponin levels, aspirin 75mg OD, cardiology referral"
    """
    subjective: Optional[str] = None    # Patient's own description
    objective: Optional[str] = None     # Measurements and observations
    assessment: Optional[str] = None    # Clinical interpretation / diagnosis
    plan: Optional[str] = None          # Treatment plan


class NLPTag(BaseModel):
    """
    NLP-extracted metadata from the note text.
    Populated asynchronously by an NLP service after the note is saved.
    Used to power clinical search and analytics.
    Example: extracting "chest pain" from free text and tagging it as a symptom.
    """
    tag_type: str       # "symptom" | "drug" | "procedure" | "anatomy"
    value: str          # e.g. "chest pain"
    confidence: float   # 0.0 to 1.0 — how confident the NLP model is
    span_start: int     # Character position in the original text
    span_end: int


class ClinicalNote(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ── Tenant isolation — MANDATORY ──
    tenant_id: str

    # ── Core references ───────────────────────────────────────────────────
    encounter_id: str
    patient_id: str       # Denormalized for faster queries without joining
    note_type: NoteType = NoteType.SOAP

    # ── Authorship ────────────────────────────────────────────────────────
    author_id: str                          # Who wrote the note
    cosigner_id: Optional[str] = None       # Senior doctor who co-signed
    supervising_doctor_id: Optional[str] = None  # For residents/trainees

    # ── SOAP content ──────────────────────────────────────────────────────
    soap: SOAPContent = Field(default_factory=SOAPContent)

    # ── Signature ─────────────────────────────────────────────────────────
    signature_status: SignatureStatus = SignatureStatus.DRAFT
    signed_at: Optional[datetime] = None
    cosigned_at: Optional[datetime] = None

    # ── Addendum chain ────────────────────────────────────────────────────
    # If this note IS an addendum, it points to the original note.
    # The original note itself is never modified — addenda chain off it.
    parent_note_id: Optional[str] = None    # Set if note_type == ADDENDUM
    # List of addendum IDs added to this note (if this is the original)
    addendum_ids: list[str] = Field(default_factory=list)

    # ── NLP metadata ──────────────────────────────────────────────────────
    # Populated after save by background NLP task
    nlp_tags: list[NLPTag] = Field(default_factory=list)
    nlp_processed_at: Optional[datetime] = None

    # ── Elasticsearch sync ────────────────────────────────────────────────
    # Tracks whether this note has been synced to Elasticsearch for search
    es_synced: bool = False
    es_synced_at: Optional[datetime] = None

    # ── Timestamps ────────────────────────────────────────────────────────
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


CLINICAL_NOTE_INDEXES = [
    # All notes for an encounter
    {
        "key": [("tenant_id", 1), ("encounter_id", 1), ("created_at", -1)],
        "name": "idx_note_tenant_encounter_date"
    },
    # All notes by a doctor
    {
        "key": [("tenant_id", 1), ("author_id", 1), ("created_at", -1)],
        "name": "idx_note_tenant_author_date"
    },
    # Notes pending Elasticsearch sync
    {
        "key": [("tenant_id", 1), ("es_synced", 1)],
        "name": "idx_note_tenant_es_synced"
    },
    # Addendum lookup
    {
        "key": [("tenant_id", 1), ("parent_note_id", 1)],
        "name": "idx_note_tenant_parent"
    },
]

COLLECTION_NAME = "clinical_notes"