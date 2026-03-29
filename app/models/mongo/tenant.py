# models/mongo/tenant.py
# The Tenant model is the top-level owner of all other data.
# Every hospital organisation that signs up is one Tenant.
# All other models reference tenant_id back to this.

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
from enum import Enum
import uuid


class SubscriptionTier(str, Enum):
    """Controls which features a tenant has access to."""
    FREE = "free"
    STANDARD = "standard"
    ENTERPRISE = "enterprise"


class RegulatoryJurisdiction(str, Enum):
    """
    Which regulatory framework applies to this tenant.
    Determines audit log retention period:
      HIPAA  → 6 years minimum
      GDPR   → variable (right to erasure complicates this)
      LOCAL  → governed by local law
    """
    HIPAA = "hipaa"
    GDPR = "gdpr"
    LOCAL = "local"


class ThemeTokens(BaseModel):
    """Branding config for the tenant's patient-facing website."""
    primary_color: str = "#1D9E75"
    logo_url: Optional[str] = None
    font_family: str = "Inter"


class TenantCreate(BaseModel):
    """Fields required to create a new tenant (used in provisioning script)."""
    name: str
    slug: str            # URL-safe identifier e.g. "city-general-hospital"
    subdomain: str       # e.g. "citygeneral" → citygeneral.hms.io
    timezone: str        # e.g. "Asia/Kolkata", "America/New_York"
    locale: str          # e.g. "en-IN", "en-US"
    jurisdiction: RegulatoryJurisdiction


class Tenant(BaseModel):
    """
    Full Tenant document stored in MongoDB.
    This is the source of truth for tenant configuration.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    slug: str                          # Unique — enforced by MongoDB unique index
    subdomain: str                     # Unique — enforced by MongoDB unique index
    subscription_tier: SubscriptionTier = SubscriptionTier.STANDARD

    # Billing metadata — what plan they're on, payment status
    billing_email: Optional[str] = None
    billing_customer_id: Optional[str] = None   # e.g. Stripe customer ID

    # Feature flags — override default features per tenant
    # Example: {"telemedicine": True, "pharmacy_module": False}
    feature_flags: dict = Field(default_factory=dict)

    # Localisation
    timezone: str
    locale: str

    # Custom domain config
    # A tenant may have multiple domains e.g. ["citygeneral.com", "www.citygeneral.com"]
    custom_domains: list[str] = Field(default_factory=list)
    ssl_cert_references: list[str] = Field(default_factory=list)

    # Patient-facing website branding
    theme: ThemeTokens = Field(default_factory=ThemeTokens)

    # Which regulatory framework applies
    jurisdiction: RegulatoryJurisdiction

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Soft delete — we never hard-delete tenant data
    # Deleted tenants are hidden from queries but data is preserved for audit
    deleted_at: Optional[datetime] = None
    is_active: bool = True


# ── MongoDB Index Definitions ──────────────────────────────────────────────
# These are created by scripts/mongo_indexes.py — not auto-created.
# tenant_id is always the leading key per ADR Decision 4.
TENANT_INDEXES = [
    {"key": [("slug", 1)], "unique": True, "name": "idx_tenant_slug_unique"},
    {"key": [("subdomain", 1)], "unique": True, "name": "idx_tenant_subdomain_unique"},
    {"key": [("is_active", 1)], "name": "idx_tenant_active"},
]

COLLECTION_NAME = "tenants"