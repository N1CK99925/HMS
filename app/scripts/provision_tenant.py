# scripts/provision_tenant.py
# Creates a new tenant and seeds all reference data.
# IDEMPOTENT — safe to run multiple times. If the tenant already exists,
# it skips creation. If ICD codes are already seeded, it skips those too.
#
# Run with: python scripts/provision_tenant.py --slug "city-general" --name "City General Hospital"

import asyncio
import argparse
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
from app.models.mongo.tenant import Tenant, RegulatoryJurisdiction, SubscriptionTier


# ── Sample ICD-10 codes (seed data) ───────────────────────────────────────
# In production, load the full ICD-10 dataset from a file.
# These are a representative sample for development.
SAMPLE_ICD_CODES = [
    {"code": "A00", "description": "Cholera"},
    {"code": "A01", "description": "Typhoid and paratyphoid fevers"},
    {"code": "E11", "description": "Type 2 diabetes mellitus"},
    {"code": "I10", "description": "Essential (primary) hypertension"},
    {"code": "J18", "description": "Pneumonia, unspecified organism"},
    {"code": "K29", "description": "Gastritis and duodenitis"},
    {"code": "M54", "description": "Dorsalgia (back pain)"},
    {"code": "N39", "description": "Other disorders of urinary system"},
    {"code": "R05", "description": "Cough"},
    {"code": "R50", "description": "Fever of other and unknown origin"},
]

# ── Sample drug master entries ─────────────────────────────────────────────
SAMPLE_DRUGS = [
    {"code": "PARA500", "name": "Paracetamol 500mg", "form": "tablet",
     "controlled": False, "interactions": []},
    {"code": "AMOX500", "name": "Amoxicillin 500mg", "form": "capsule",
     "controlled": False, "interactions": []},
    {"code": "METF500", "name": "Metformin 500mg", "form": "tablet",
     "controlled": False, "interactions": ["WARN_RENAL"]},
    {"code": "ATOR10", "name": "Atorvastatin 10mg", "form": "tablet",
     "controlled": False, "interactions": []},
    {"code": "MORPH10", "name": "Morphine 10mg", "form": "injection",
     "controlled": True, "schedule": "Schedule H1",
     "interactions": ["CNS_DEPRESSANT"]},
]

# ── Specialty taxonomy ────────────────────────────────────────────────────
SPECIALTIES = [
    "general_medicine", "cardiology", "neurology", "orthopedics",
    "pediatrics", "obstetrics_gynecology", "psychiatry", "dermatology",
    "ophthalmology", "ent", "general_surgery", "radiology",
    "pathology", "anesthesiology", "emergency_medicine",
]


async def provision_tenant(slug: str, name: str, timezone: str = "Asia/Kolkata",
                           locale: str = "en-IN"):
    """
    Creates a new tenant and seeds all reference data.
    Idempotent — checks before creating anything.
    """
    client = AsyncIOMotorClient(settings.MONGO_URL)
    db = client[settings.MONGO_DB_NAME]

    print(f"\nProvisioning tenant: {name} ({slug})")

    # ── Step 1: Create tenant (skip if exists) ─────────────────────────────
    existing = await db["tenants"].find_one({"slug": slug})
    if existing:
        print(f"  Tenant '{slug}' already exists — skipping creation")
        tenant_id = existing["id"]
    else:
        tenant = Tenant(
            name=name,
            slug=slug,
            subdomain=slug.replace("-", ""),   # "city-general" → "citygeneral"
            timezone=timezone,
            locale=locale,
            jurisdiction=RegulatoryJurisdiction.LOCAL,
            subscription_tier=SubscriptionTier.STANDARD,
        )
        await db["tenants"].insert_one(tenant.model_dump())
        tenant_id = tenant.id
        print(f"  Tenant created: id={tenant_id}")

    # ── Step 2: Seed ICD codes (skip if already seeded for this tenant) ────
    icd_count = await db["icd_codes"].count_documents({"tenant_id": tenant_id})
    if icd_count > 0:
        print(f"  ICD codes already seeded ({icd_count} records) — skipping")
    else:
        icd_docs = [
            {"tenant_id": tenant_id, "code": c["code"],
             "description": c["description"], "version": "ICD-10",
             "created_at": datetime.utcnow()}
            for c in SAMPLE_ICD_CODES
        ]
        await db["icd_codes"].insert_many(icd_docs)
        print(f"  Seeded {len(icd_docs)} ICD codes")

    # ── Step 3: Seed drug master (skip if already seeded) ─────────────────
    drug_count = await db["drug_master"].count_documents({"tenant_id": tenant_id})
    if drug_count > 0:
        print(f"  Drug master already seeded ({drug_count} records) — skipping")
    else:
        drug_docs = [
            {"tenant_id": tenant_id, **drug, "created_at": datetime.utcnow()}
            for drug in SAMPLE_DRUGS
        ]
        await db["drug_master"].insert_many(drug_docs)
        print(f"  Seeded {len(drug_docs)} drugs")

    # ── Step 4: Seed specialty taxonomy ───────────────────────────────────
    spec_count = await db["specialties"].count_documents({"tenant_id": tenant_id})
    if spec_count > 0:
        print(f"  Specialties already seeded — skipping")
    else:
        spec_docs = [
            {"tenant_id": tenant_id, "code": s, "name": s.replace("_", " ").title(),
             "created_at": datetime.utcnow()}
            for s in SPECIALTIES
        ]
        await db["specialties"].insert_many(spec_docs)
        print(f"  Seeded {len(spec_docs)} specialties")

    print(f"\nTenant '{name}' is ready. tenant_id = {tenant_id}\n")
    client.close()
    return tenant_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True, help="URL-safe tenant identifier")
    parser.add_argument("--name", required=True, help="Human-readable hospital name")
    parser.add_argument("--timezone", default="Asia/Kolkata")
    parser.add_argument("--locale", default="en-IN")
    args = parser.parse_args()

    asyncio.run(provision_tenant(
        slug=args.slug,
        name=args.name,
        timezone=args.timezone,
        locale=args.locale,
    ))