# app/models/mongo/lab_order.py
# Lab orders are created by doctors and fulfilled by lab technicians.
#
# Key design decisions:
#
# 1. PANELS vs INDIVIDUAL TESTS
#    A doctor can order a panel (e.g. "Complete Blood Count") which
#    automatically includes multiple individual tests. Or they can
#    order individual tests directly. Both are supported.
#
# 2. REFERENCE RANGE VERSIONING (ADR Error 6 fix)
#    Normal ranges change as medical standards update. A result must
#    always be evaluated against the range that was current at the
#    time the test was run — not today's range.
#    We store the reference_range_version_id on every result.
#
# 3. CRITICAL VALUE ACKNOWLEDGEMENT
#    If a result is critically abnormal, the lab marks it critical.
#    The system alerts the doctor. The doctor must acknowledge the
#    alert — and that acknowledgement is audited.

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum
import uuid


class LabOrderStatus(str, Enum):
    PENDING         = "pending"       # Ordered, not yet collected
    COLLECTED       = "collected"     # Specimen collected, awaiting processing
    IN_PROGRESS     = "in_progress"   # Being processed in the lab
    RESULTED        = "resulted"      # Results available
    CANCELLED       = "cancelled"


class SpecimenType(str, Enum):
    BLOOD           = "blood"
    URINE           = "urine"
    STOOL           = "stool"
    SPUTUM          = "sputum"
    SWAB            = "swab"
    CSF             = "csf"           # Cerebrospinal fluid
    TISSUE          = "tissue"        # Biopsy
    OTHER           = "other"


class ReferenceRange(BaseModel):
    """
    ADR Error 6 fix: reference ranges are versioned.
    A result stores the version ID at time of testing — not the current range.
    This ensures historical results remain medically accurate even after
    range updates due to new medical guidelines.
    """
    version_id: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    unit: str
    # Some ranges vary by age and sex — stored here for the snapshot
    applicable_age_min: Optional[int] = None
    applicable_age_max: Optional[int] = None
    applicable_sex: Optional[str] = None   # "male" | "female" | "all"
    notes: Optional[str] = None


class LabResult(BaseModel):
    """
    One result within a lab order.
    A single order (e.g. CBC panel) can have many results (WBC, RBC, HGB etc.)
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    test_code: str              # e.g. "WBC", "HGB", "CREATININE"
    test_name: str              # Human readable name
    value: str                  # Stored as string — handles both numeric and text results
    numeric_value: Optional[float] = None  # Stored separately for range comparison
    unit: str                   # e.g. "g/dL", "10^3/µL", "mg/dL"

    # Reference range snapshot at time of result
    reference_range: Optional[ReferenceRange] = None
    reference_range_version_id: Optional[str] = None

    # Interpretation
    is_abnormal: bool = False
    abnormal_flag: Optional[str] = None  # "H" high | "L" low | "HH" critically high | "LL" critically low

    # Critical value — requires immediate doctor notification
    is_critical: bool = False
    critical_acknowledged: bool = False
    critical_acknowledged_by_id: Optional[str] = None
    critical_acknowledged_at: Optional[datetime] = None

    # Who entered this result
    resulted_by_id: str = None           # Lab technician staff ID
    resulted_at: datetime = Field(default_factory=datetime.utcnow)

    # HL7 FHIR R4 — store the raw FHIR Observation bundle reference
    # We don't store the full FHIR JSON here — just a reference to where it lives
    fhir_observation_id: Optional[str] = None


class SpecimenCollection(BaseModel):
    """Records the physical act of collecting the specimen."""
    collected_at: datetime
    collected_by_id: str        # Staff ID of nurse or phlebotomist
    specimen_type: SpecimenType
    specimen_id: str            # Barcode/label on the physical specimen tube
    notes: Optional[str] = None


class LabOrder(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ── Tenant isolation — MANDATORY ──
    tenant_id: str

    # ── Core references ───────────────────────────────────────────────────
    encounter_id: str
    patient_id: str             # Denormalized for worklist queries
    ordering_doctor_id: str
    department_id: str          # Which lab department handles this

    # ── What was ordered ──────────────────────────────────────────────────
    # Either a panel or individual tests — not both
    panel_code: Optional[str] = None      # e.g. "CBC", "LFT", "KFT"
    panel_name: Optional[str] = None
    individual_test_codes: list[str] = Field(default_factory=list)

    # Clinical context — why was this ordered?
    clinical_indication: Optional[str] = None  # e.g. "Rule out anaemia"
    priority: str = "routine"   # "routine" | "urgent" | "stat"

    # ── Specimen ──────────────────────────────────────────────────────────
    specimen_type: SpecimenType = SpecimenType.BLOOD
    specimen_collection: Optional[SpecimenCollection] = None

    # ── Status ────────────────────────────────────────────────────────────
    status: LabOrderStatus = LabOrderStatus.PENDING

    # ── Results ───────────────────────────────────────────────────────────
    # Results are embedded in the order document — they always belong together
    results: list[LabResult] = Field(default_factory=list)

    # ── Timestamps ────────────────────────────────────────────────────────
    ordered_at: datetime = Field(default_factory=datetime.utcnow)
    resulted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


LAB_ORDER_INDEXES = [
    # Lab technician worklist — critical query path Q4
    # "Give me all pending orders for the pathology department"
    {
        "key": [("tenant_id", 1), ("department_id", 1), ("status", 1), ("ordered_at", 1)],
        "name": "idx_laborder_tenant_dept_status_date"
    },
    # All lab orders for an encounter
    {
        "key": [("tenant_id", 1), ("encounter_id", 1)],
        "name": "idx_laborder_tenant_encounter"
    },
    # All lab orders for a patient (history)
    {
        "key": [("tenant_id", 1), ("patient_id", 1), ("ordered_at", -1)],
        "name": "idx_laborder_tenant_patient_date"
    },
    # Critical unacknowledged results — for alert dashboard
    {
        "key": [("tenant_id", 1), ("status", 1)],
        "name": "idx_laborder_tenant_status"
    },
]

COLLECTION_NAME = "lab_orders"