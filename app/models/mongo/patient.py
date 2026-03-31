# models/mongo/patient.py
# Patient is the most sensitive model in the system.
# All fields here are PHI (Protected Health Information).
# Every read of this collection triggers an audit log write.

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, date, timezone
from enum import Enum
import uuid


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class BloodGroup(str, Enum):
    A_POS = "A+"
    A_NEG = "A-"
    B_POS = "B+"
    B_NEG = "B-"
    AB_POS = "AB+"
    AB_NEG = "AB-"
    O_POS = "O+"
    O_NEG = "O-"


class EmergencyContact(BaseModel):
    """
    A patient can have multiple emergency contacts.
    Relationship uses a taxonomy rather than free text
    so it's consistent across tenants for analytics.
    """
    name: str
    relationship: str      # e.g. "spouse", "parent", "sibling", "child", "guardian"
    phone: str
    is_primary: bool = False


class InsurancePolicy(BaseModel):
    """
    A patient may have multiple concurrent insurance policies:
    primary, secondary, and tertiary — matching our billing model.
    """
    payer_name: str
    member_id: str
    group_number: Optional[str] = None
    policy_type: str    # "primary" | "secondary" | "tertiary"
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    is_active: bool = True


class ConsentVersion(BaseModel):
    """
    Tracks which version of consent forms the patient has agreed to.
    Required for HIPAA — you must know what consent was in effect at time of treatment.
    """
    version: str
    signed_at: datetime
    signed_by_ip: Optional[str] = None


class NationalIdentifier(BaseModel):
    """
    Different countries use different national ID systems.
    We store the type and value rather than a single hardcoded field
    so the system works for India (Aadhaar), UK (NHS), US (SSN), etc.
    """
    id_type: str    # "aadhaar" | "ssn" | "nhs_number" | "passport" | etc.
    value: str      # Encrypted at rest — never store plain text national IDs


class Patient(BaseModel):
    """
    Full Patient document. This is PHI — handle with care.

    Key design decisions:
    - MRN is tenant-scoped unique (two hospitals can have patient #001 — that's fine)
    - national_identifiers is a list because someone may have Aadhaar + passport
    - insurance_policies is a list for primary/secondary/tertiary coverage
    - emergency_contacts is a list — patient may have multiple
    - consent_versions is append-only — we never remove old consent records
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ── Tenant isolation — MANDATORY on every model ──
    tenant_id: str     # Non-nullable. Set by middleware from JWT. Never trust user input.

    # ── Core identifiers ─────────────────────────────
    mrn: str           # Medical Record Number. Unique within this tenant only.

    # Biometric reference — we store a reference ID to an external biometric store,
    # not the biometric data itself (fingerprint hash etc.)
    biometric_reference_id: Optional[str] = None

    # National IDs stored as a list — patient may have multiple
    national_identifiers: list[NationalIdentifier] = Field(default_factory=list)

    # ── Demographics ──────────────────────────────────
    first_name: str
    last_name: str
    date_of_birth: date
    gender: Gender
    blood_group: Optional[BloodGroup] = None

    # ── Contact ───────────────────────────────────────
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    language_preference: str = "en"    # IETF language tag e.g. "en", "hi", "ta"

    # ── Clinical references ───────────────────────────
    preferred_doctor_id: Optional[str] = None   # Staff ID

    # ── Insurance ─────────────────────────────────────
    insurance_policies: list[InsurancePolicy] = Field(default_factory=list)

    # ── Emergency contacts ────────────────────────────
    emergency_contacts: list[EmergencyContact] = Field(default_factory=list)

    # ── Consent ───────────────────────────────────────
    # Append-only list — each new consent version is added, old ones never removed
    consent_versions: list[ConsentVersion] = Field(default_factory=list)

    # ── Deceased flag ─────────────────────────────────
    # We never delete patient records — we mark them deceased
    is_deceased: bool = False
    deceased_at: Optional[datetime] = None

    # ── Timestamps ────────────────────────────────────
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Soft delete — same as tenant model
    deleted_at: Optional[datetime] = None


# ── MongoDB Index Definitions ─────────────────────────────────────────────
# Per ADR Decision 4: tenant_id is ALWAYS the leading key.
# Without tenant_id first, a query for mrn="001" would scan ALL tenants.
PATIENT_INDEXES = [
    # MRN lookup — most common query at reception desk
    # Unique within a tenant — two tenants can both have MRN "P001"
    {
        "key": [("tenant_id", 1), ("mrn", 1)],
        "unique": True,
        "name": "idx_patient_tenant_mrn_unique"
    },
    # ID lookup — for direct access by internal ID
    {
        "key": [("id", 1), ("tenant_id", 1)],
        "unique": True,
        "name": "idx_patient_id_tenant_unique"
    },
    # Name search — for receptionist lookup
    {
        "key": [("tenant_id", 1), ("last_name", 1), ("first_name", 1)],
        "name": "idx_patient_tenant_name"
    },
    # Preferred doctor filter
    {
        "key": [("tenant_id", 1), ("preferred_doctor_id", 1)],
        "name": "idx_patient_tenant_doctor"
    },
    # Active patients only (soft delete support)
    {
        "key": [("tenant_id", 1), ("deleted_at", 1)],
        "name": "idx_patient_tenant_deleted"
    },
]

COLLECTION_NAME = "patients"