
from sqlalchemy import (
    Column, String, Float, Integer, DateTime, Boolean,
    ForeignKey, Text, Enum as SAEnum, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
from enum import Enum
import uuid

from app.core.database import Base


# ─────────────────────────────────────────────
# CHARGE MASTER
# The fee schedule — what each service costs.
# Tenant-customisable: each hospital sets their own prices.
# ─────────────────────────────────────────────

class ChargeMaster(Base):
    """
    Defines the price of every billable service or item.
    Each tenant maintains their own fee schedule.
    Example rows:
      - "OPD Consultation" → ₹500
      - "Blood CBC Panel"  → ₹350
      - "Chest X-Ray"      → ₹800
    """
    __tablename__ = "charge_master"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Tenant isolation — every financial table has this
    tenant_id = Column(String, nullable=False, index=True)

    # The service being billed
    service_code = Column(String(50), nullable=False)     # CPT or internal code
    service_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Pricing
    unit_price = Column(Float, nullable=False)
    currency = Column(String(3), default="INR")           # ISO 4217 currency code

    # ICD/CPT linkage for insurance claims
    cpt_code = Column(String(20), nullable=True)
    icd_code = Column(String(20), nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    charge_lines = relationship("BillingChargeLine", back_populates="charge_item")

    # Indexes
    __table_args__ = (
        # Service code must be unique per tenant
        UniqueConstraint("tenant_id", "service_code", name="uq_charge_tenant_code"),
        Index("idx_charge_tenant_active", "tenant_id", "is_active"),
    )


# ─────────────────────────────────────────────
# BILLING
# One bill per encounter.
# Links the clinical world (MongoDB encounter_id) to the financial world (PostgreSQL).
# ─────────────────────────────────────────────

class BillingStatus(str, Enum):
    DRAFT = "draft"
    FINALISED = "finalised"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    WRITTEN_OFF = "written_off"
    CANCELLED = "cancelled"


class Billing(Base):
    """
    One bill per encounter. The bridge between MongoDB (clinical) and
    PostgreSQL (financial). The encounter_id references a MongoDB document.
    """
    __tablename__ = "billing"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String, nullable=False, index=True)

    # Reference to MongoDB encounter — cross-DB link (application-layer join)
    encounter_id = Column(String, nullable=False)

    # Reference to MongoDB patient — for quick billing lookups
    patient_id = Column(String, nullable=False)

    # Amounts
    subtotal = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    tax_amount = Column(Float, default=0.0)
    total_amount = Column(Float, nullable=False)

    # What the patient paid out of pocket
    copay_amount = Column(Float, default=0.0)
    copay_collected = Column(Float, default=0.0)   # May be less than copay_amount

    # Write-off — amount the hospital forgives (charity, error correction)
    write_off_amount = Column(Float, default=0.0)
    write_off_reason = Column(String(255), nullable=True)

    status = Column(SAEnum(BillingStatus), default=BillingStatus.DRAFT, nullable=False)
    currency = Column(String(3), default="INR")

    # Who generated this bill
    generated_by_staff_id = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    charge_lines = relationship("BillingChargeLine", back_populates="bill")
    insurance_claims = relationship("InsuranceClaim", back_populates="bill")

    __table_args__ = (
        # Look up all bills for a patient
        Index("idx_billing_tenant_patient", "tenant_id", "patient_id"),
        # Look up all bills by status (finance dashboard)
        Index("idx_billing_tenant_status", "tenant_id", "status"),
        # One bill per encounter (enforced)
        UniqueConstraint("tenant_id", "encounter_id", name="uq_billing_tenant_encounter"),
    )


class BillingChargeLine(Base):
    """
    Individual line items on a bill.
    One bill has many charge lines.
    Example: OPD Consultation + Blood Test + Medication = 3 charge lines.
    """
    __tablename__ = "billing_charge_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String, nullable=False)
    bill_id = Column(UUID(as_uuid=True), ForeignKey("billing.id"), nullable=False)
    charge_master_id = Column(UUID(as_uuid=True), ForeignKey("charge_master.id"), nullable=True)

    # Snapshot of the price at time of billing
    # We store this separately because charge_master prices may change later
    service_name = Column(String(255), nullable=False)
    unit_price = Column(Float, nullable=False)
    quantity = Column(Integer, default=1)
    line_total = Column(Float, nullable=False)

    # Relationships
    bill = relationship("Billing", back_populates="charge_lines")
    charge_item = relationship("ChargeMaster", back_populates="charge_lines")

    __table_args__ = (
        Index("idx_chargeline_bill", "bill_id"),
    )


# ─────────────────────────────────────────────
# INSURANCE CLAIM
# State machine: draft → submitted → adjudicated → paid/denied/appealed
# One bill can have up to 3 claims (primary / secondary / tertiary payer).
# ─────────────────────────────────────────────

class ClaimStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    ADJUDICATED = "adjudicated"
    PAID = "paid"
    DENIED = "denied"
    APPEALED = "appealed"
    WRITE_OFF = "write_off"


class PayerTier(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TERTIARY = "tertiary"


class InsuranceClaim(Base):
    """
    Insurance claim lifecycle.
    Each claim goes through a strict state machine —
    invalid transitions are rejected at the application layer.

    A single bill can have:
      - 1 primary claim  (patient's main insurance)
      - 1 secondary claim (spouse's insurance)
      - 1 tertiary claim  (additional coverage)
    """
    __tablename__ = "insurance_claims"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String, nullable=False)
    bill_id = Column(UUID(as_uuid=True), ForeignKey("billing.id"), nullable=False)

    # Payer details
    payer_name = Column(String(255), nullable=False)
    payer_id = Column(String(100), nullable=True)        # Payer's system ID
    payer_tier = Column(SAEnum(PayerTier), nullable=False)

    # Patient's policy details at time of claim
    member_id = Column(String(100), nullable=False)
    group_number = Column(String(100), nullable=True)

    # Amounts
    billed_amount = Column(Float, nullable=False)         # What we charged
    claimed_amount = Column(Float, nullable=False)        # What we're claiming
    adjudicated_amount = Column(Float, nullable=True)     # What insurer approved
    paid_amount = Column(Float, nullable=True)            # What was actually paid
    denied_amount = Column(Float, nullable=True)

    # State machine
    status = Column(SAEnum(ClaimStatus), default=ClaimStatus.DRAFT, nullable=False)
    denial_reason = Column(Text, nullable=True)
    appeal_notes = Column(Text, nullable=True)

    # ERA / EOB reference
    # ERA = Electronic Remittance Advice (what insurer paid)
    # EOB = Explanation of Benefits (what patient owes)
    era_reference = Column(String(255), nullable=True)
    eob_reference = Column(String(255), nullable=True)

    # Timestamps for each state transition
    submitted_at = Column(DateTime, nullable=True)
    adjudicated_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    bill = relationship("Billing", back_populates="insurance_claims")

    __table_args__ = (
        # Critical query path Q6 from ADR: claims by payer and status
        Index("idx_claim_tenant_payer_status", "tenant_id", "payer_id", "status"),
        # Finance dashboard: all claims by status
        Index("idx_claim_tenant_status_date", "tenant_id", "status", "submitted_at"),
        # One claim per payer tier per bill
        UniqueConstraint("bill_id", "payer_tier", name="uq_claim_bill_payer_tier"),
    )


# ─────────────────────────────────────────────
# AUDIT LOG
# Immutable. Append-only. One record per PHI access or write.
# Application credentials have NO DELETE privilege on this table.
# This is enforced at the PostgreSQL user permission level.
# ─────────────────────────────────────────────

class AuditAction(str, Enum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    # No DELETE — we soft-delete. A DELETE audit entry means something went wrong.
    SOFT_DELETE = "soft_delete"
    EXPORT = "export"
    PRINT = "print"


class AuditLog(Base):
    """
    Every PHI access or write creates one of these.
    Written SYNCHRONOUSLY before the API response is returned.
    Never goes through RabbitMQ — too important to risk losing.

    Tamper evidence: we store hashes of the before/after state,
    not the full record. This keeps the audit table small while
    still detecting modifications.
    """
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Who did it
    tenant_id = Column(String, nullable=False)
    actor_id = Column(String, nullable=False)       # Staff ID from JWT
    actor_role = Column(String, nullable=False)     # Their role at time of access

    # What they did
    action = Column(SAEnum(AuditAction), nullable=False)
    resource_type = Column(String(100), nullable=False)   # e.g. "patient", "prescription"
    resource_id = Column(String, nullable=False)           # The document/row ID

    # Tamper evidence — hashes of state before and after
    # We use SHA-256 of the JSON-serialised document
    prev_state_hash = Column(String(64), nullable=True)   # None for CREATE actions
    new_state_hash = Column(String(64), nullable=True)    # None for READ/DELETE

    # Why they accessed it (required for support agents — see ADR Decision 3)
    access_justification_code = Column(String(50), nullable=True)
    justification_notes = Column(Text, nullable=True)

    # When — always UTC
    accessed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # IP address and user agent for forensics
    ip_address = Column(String(45), nullable=True)    # 45 chars covers IPv6
    user_agent = Column(String(500), nullable=True)

    __table_args__ = (
        # Critical query path Q7 from ADR: compliance officer lookup by actor + date
        Index("idx_audit_tenant_actor_date", "tenant_id", "actor_id", "accessed_at"),
        # Look up all accesses to a specific record (e.g. who viewed patient X?)
        Index("idx_audit_resource", "tenant_id", "resource_type", "resource_id"),
        # Date range queries for retention/purge
        Index("idx_audit_date", "accessed_at"),
    )