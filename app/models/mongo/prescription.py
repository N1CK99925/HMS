# app/models/mongo/prescription.py
# Prescriptions are medication orders written during an encounter.
# Two safety rules enforced here:
#
# 1. DRUG INTERACTION CHECK — before saving, the service checks the new drug
#    against all active prescriptions for this patient. If a dangerous
#    interaction is found, the prescription is blocked.
#
# 2. CONTROLLED SUBSTANCE FLAG — drugs on the controlled list have extra
#    fields: schedule, authorization code, and dispense tracking.
#    These cannot be refilled without a new prescription.

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, date
from enum import Enum
import uuid


class PrescriptionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"       # Full course taken
    CANCELLED = "cancelled"       # Doctor cancelled before dispensing
    EXPIRED = "expired"           # Past expiry date
    ON_HOLD = "on_hold"           # Temporarily paused


class RouteOfAdministration(str, Enum):
    ORAL = "oral"                 # By mouth (tablet, syrup)
    IV = "iv"                     # Intravenous
    IM = "im"                     # Intramuscular injection
    SC = "sc"                     # Subcutaneous injection
    TOPICAL = "topical"           # Applied to skin
    INHALED = "inhaled"           # Inhaler / nebuliser
    SUBLINGUAL = "sublingual"     # Under the tongue
    RECTAL = "rectal"
    OPHTHALMIC = "ophthalmic"     # Eye drops


class SigCode(BaseModel):
    """
    Structured dosage instructions — called a 'sig' in pharmacy.
    Stored structured (not free text) so the pharmacy system can parse it.

    Example sig: "Take 1 tablet twice daily after meals for 5 days"
    Structured as:
      dose_quantity: 1
      dose_unit: "tablet"
      frequency: "BD" (twice daily)
      timing: "after meals"
      duration_days: 5
    """
    dose_quantity: float          # How much e.g. 1, 0.5, 2
    dose_unit: str                # "tablet" | "ml" | "mg" | "drop" | "puff"
    frequency: str                # "OD" once daily | "BD" twice | "TDS" thrice | "QID" four times
    timing: Optional[str] = None  # "after meals" | "before bed" | "with food"
    duration_days: Optional[int] = None   # None = ongoing (chronic medication)
    prn_condition: Optional[str] = None   # PRN = as needed. e.g. "for pain"
    is_prn: bool = False          # PRN means "take only when needed"


class DispenseEvent(BaseModel):
    """
    Records each time a prescription was dispensed at the pharmacy.
    A prescription with refills=3 will have up to 3 dispense events.
    """
    dispensed_at: datetime
    dispensed_by_pharmacist_id: str
    quantity_dispensed: float
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None
    notes: Optional[str] = None


class DrugInteractionFlag(BaseModel):
    """
    Recorded when a drug interaction is detected at prescription time.
    Even if the doctor overrides the warning, we record it here.
    This creates an audit trail of clinical decisions.
    """
    interacting_drug_id: str
    interacting_drug_name: str
    severity: str           # "mild" | "moderate" | "severe" | "contraindicated"
    description: str        # Plain English explanation of the interaction
    overridden: bool = False
    override_reason: Optional[str] = None
    override_by_doctor_id: Optional[str] = None


class Prescription(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ── Tenant isolation — MANDATORY ──
    tenant_id: str

    # ── Core references ───────────────────────────────────────────────────
    encounter_id: str
    patient_id: str       # Denormalized for active prescription lookup
    prescribing_doctor_id: str

    # ── Drug ──────────────────────────────────────────────────────────────
    drug_id: str          # Reference to drug_master collection
    drug_name: str        # Denormalized snapshot — drug_master name may change
    drug_code: str        # Denormalized snapshot — for dispense tracking

    # ── Dosage instructions (structured sig) ──────────────────────────────
    sig: SigCode

    # ── Route of administration ───────────────────────────────────────────
    route: RouteOfAdministration = RouteOfAdministration.ORAL

    # ── Refills ───────────────────────────────────────────────────────────
    refills_authorised: int = 0      # How many refills are allowed
    refills_remaining: int = 0       # Decrements each time it's dispensed

    # ── Controlled substance ──────────────────────────────────────────────
    # Controlled substances have strict dispensing and record-keeping rules
    is_controlled_substance: bool = False
    controlled_schedule: Optional[str] = None   # "Schedule H" | "Schedule H1" | "Schedule X"
    controlled_auth_code: Optional[str] = None  # Authorization reference number

    # ── Status and dates ──────────────────────────────────────────────────
    status: PrescriptionStatus = PrescriptionStatus.ACTIVE
    prescribed_at: datetime = Field(default_factory=datetime.utcnow)
    valid_until: Optional[date] = None    # Prescription expiry date

    # ── Interaction flags ─────────────────────────────────────────────────
    # Populated by the drug interaction check service before saving
    interaction_flags: list[DrugInteractionFlag] = Field(default_factory=list)

    # ── Dispense history ──────────────────────────────────────────────────
    dispense_events: list[DispenseEvent] = Field(default_factory=list)

    # ── Timestamps ────────────────────────────────────────────────────────
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


PRESCRIPTION_INDEXES = [
    # Active prescriptions for a patient — critical for drug interaction check (Q5)
    {
        "key": [("tenant_id", 1), ("patient_id", 1), ("status", 1)],
        "name": "idx_rx_tenant_patient_status"
    },
    # All prescriptions for an encounter
    {
        "key": [("tenant_id", 1), ("encounter_id", 1)],
        "name": "idx_rx_tenant_encounter"
    },
    # Prescriptions by doctor
    {
        "key": [("tenant_id", 1), ("prescribing_doctor_id", 1), ("prescribed_at", -1)],
        "name": "idx_rx_tenant_doctor_date"
    },
    # Controlled substance audit — must be fast
    {
        "key": [("tenant_id", 1), ("is_controlled_substance", 1), ("status", 1)],
        "name": "idx_rx_tenant_controlled"
    },
    # Expiry monitoring — find prescriptions expiring soon
    {
        "key": [("tenant_id", 1), ("valid_until", 1), ("status", 1)],
        "name": "idx_rx_tenant_expiry_status"
    },
]

COLLECTION_NAME = "prescriptions"