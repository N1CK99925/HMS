# app/models/mongo/encounter.py
# An encounter is one clinical visit — OPD, IPD, Emergency, or Telemedicine.
# Everything that happens to a patient during a visit hangs off this document.
# It is the central clinical entity — lab orders, notes, prescriptions all
# reference the encounter_id.

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum
import uuid


class EncounterType(str, Enum):
    OPD = "opd"               # Outpatient — patient comes and leaves same day
    IPD = "ipd"               # Inpatient — patient admitted, stays overnight+
    EMERGENCY = "emergency"   # Emergency department visit
    TELE = "tele"             # Telemedicine / video call


class EncounterStatus(str, Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class DiagnosisCode(BaseModel):
    """
    ICD-10/11 diagnosis code attached to an encounter.
    We store both primary and secondary diagnoses.
    Why structured and not free text?
    Because insurance claims require coded diagnoses — free text is unbillable.
    """
    code: str               # e.g. "I10" for hypertension
    description: str        # e.g. "Essential (primary) hypertension"
    code_system: str = "ICD-10"   # "ICD-10" or "ICD-11"
    is_primary: bool = False       # Only one diagnosis should be primary


class ChiefComplaint(BaseModel):
    """
    ADR Error 1 fix: dual field — structured code + free text.
    The SNOMED code enables analytics and clinical decision support.
    The narrative preserves the doctor's exact wording.
    Both are mandatory — never one without the other.
    """
    snomed_code: str        # e.g. "29857009" = chest pain
    snomed_display: str     # e.g. "Chest pain"
    narrative: str          # Doctor's own words: "Sharp pain radiating to left arm"


class WardBedAssignment(BaseModel):
    """
    IPD patients move between wards and beds.
    We store full history — not just current assignment.
    """
    ward: str
    bed_number: str
    assigned_at: datetime
    released_at: Optional[datetime] = None


class Encounter(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ── Tenant isolation — MANDATORY ──
    tenant_id: str

    # ── Core references ───────────────────────────────────────────────────
    patient_id: str
    encounter_type: EncounterType
    status: EncounterStatus = EncounterStatus.SCHEDULED

    # ── Clinical staff ────────────────────────────────────────────────────
    admitting_doctor_id: str
    department_id: str

    # ── Chief complaint — structured + free text (ADR Error 1 fix) ───────
    chief_complaint: Optional[ChiefComplaint] = None

    # ── Diagnosis codes — list because primary + secondary ────────────────
    diagnosis_codes: list[DiagnosisCode] = Field(default_factory=list)

    # ── Timing ────────────────────────────────────────────────────────────
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None       # None = still in progress

    # ── IPD specific ──────────────────────────────────────────────────────
    # Full history of ward/bed assignments during this encounter
    ward_bed_history: list[WardBedAssignment] = Field(default_factory=list)
    discharge_summary_id: Optional[str] = None  # Reference to discharge note

    # ── Telemedicine specific ─────────────────────────────────────────────
    telehealth_meeting_link: Optional[str] = None
    telehealth_platform: Optional[str] = None   # "zoom" | "teams" | "custom"

    # ── Linked records ────────────────────────────────────────────────────
    # These are populated as the encounter progresses
    billing_id: Optional[str] = None   # PostgreSQL billing record ID

    # ── Timestamps ────────────────────────────────────────────────────────
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


ENCOUNTER_INDEXES = [
    # Patient encounter history — critical query path Q2
    {
        "key": [("tenant_id", 1), ("patient_id", 1), ("started_at", -1)],
        "name": "idx_encounter_tenant_patient_date"
    },
    # Doctor's list of encounters (their workload today)
    {
        "key": [("tenant_id", 1), ("admitting_doctor_id", 1), ("started_at", -1)],
        "name": "idx_encounter_tenant_doctor_date"
    },
    # Department-level analytics
    {
        "key": [("tenant_id", 1), ("department_id", 1), ("status", 1)],
        "name": "idx_encounter_tenant_dept_status"
    },
    # Active encounters only
    {
        "key": [("tenant_id", 1), ("status", 1)],
        "name": "idx_encounter_tenant_status"
    },
]

COLLECTION_NAME = "encounters"