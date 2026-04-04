# app/middleware/audit.py
# Writes an immutable audit record for every PHI access or write.
#
# CRITICAL RULES from ADR Decision 5.1:
# 1. Audit writes are SYNCHRONOUS — they complete before the response returns
# 2. Audit writes BYPASS RabbitMQ — too important to risk losing
# 3. The audit table has NO DELETE privilege for application credentials
# 4. We store state HASHES — not full document copies — for tamper evidence
#
# This is not a Starlette middleware — it's a helper function called
# explicitly inside route handlers. This gives routes control over
# WHAT they log (resource type, action, previous state).
#
# Usage in any route:
#   await write_phi_audit(
#       request=request,
#       action=AuditAction.READ,
#       resource_type="patient",
#       resource_id=patient_id,
#       prev_doc=None,
#       new_doc=patient_doc,
#   )

import hashlib
import json
from datetime import datetime
from typing import Optional
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.postgres.billing import AuditAction


def _hash_document(doc: Optional[dict]) -> Optional[str]:
    """
    Creates a SHA-256 hash of a document for tamper evidence.
    We hash the document, not store it, for two reasons:
    1. Keeps the audit table small — one hash per record, not a full copy
    2. The hash detects any modification to the original record
    If someone modifies a patient record and then tries to modify the
    corresponding audit entry, the hash comparison will reveal the tampering.
    """
    if doc is None:
        return None
    # Sort keys for deterministic serialisation — same doc always same hash
    serialised = json.dumps(doc, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()


async def write_phi_audit(
    request: Request,
    action: AuditAction,
    resource_type: str,
    resource_id: str,
    prev_doc: Optional[dict] = None,
    new_doc: Optional[dict] = None,
    justification_code: Optional[str] = None,
    justification_notes: Optional[str] = None,
):
    """
    Writes one immutable audit record to PostgreSQL.
    Called synchronously inside route handlers — before returning response.

    Parameters:
        request       — FastAPI request (provides actor identity + IP)
        action        — What happened (READ, CREATE, UPDATE, SOFT_DELETE etc.)
        resource_type — What was accessed ("patient", "prescription" etc.)
        resource_id   — The ID of the specific record accessed
        prev_doc      — The document BEFORE the change (None for reads/creates)
        new_doc       — The document AFTER the change (None for reads/deletes)
        justification_code  — Required for support agents
        justification_notes — Free text explanation (required for support agents)
    """
    actor_id   = getattr(request.state, "user_id",   "unknown")
    tenant_id  = getattr(request.state, "tenant_id", "unknown")
    roles      = getattr(request.state, "roles",     [])
    actor_role = roles[0] if roles else "unknown"

    # Get client IP — check X-Forwarded-For first (behind load balancer)
    ip_address = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
    user_agent = request.headers.get("User-Agent")

    audit_record = {
        "tenant_id":                tenant_id,
        "actor_id":                 actor_id,
        "actor_role":               actor_role,
        "action":                   action.value,
        "resource_type":            resource_type,
        "resource_id":              resource_id,
        "prev_state_hash":          _hash_document(prev_doc),
        "new_state_hash":           _hash_document(new_doc),
        "access_justification_code": justification_code,
        "justification_notes":      justification_notes,
        "accessed_at":              datetime.utcnow(),
        "ip_address":               ip_address,
        "user_agent":               user_agent,
    }

    # Write directly to PostgreSQL — synchronous, no queue
    # Using a fresh session (not the request-scoped one) so the audit
    # write succeeds even if the main request transaction is rolled back
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO audit_logs (
                    id, tenant_id, actor_id, actor_role,
                    action, resource_type, resource_id,
                    prev_state_hash, new_state_hash,
                    access_justification_code, justification_notes,
                    accessed_at, ip_address, user_agent
                ) VALUES (
                    gen_random_uuid(), :tenant_id, :actor_id, :actor_role,
                    :action, :resource_type, :resource_id,
                    :prev_state_hash, :new_state_hash,
                    :access_justification_code, :justification_notes,
                    :accessed_at, :ip_address, :user_agent
                )
            """),
            audit_record
        )
        await session.commit()


def require_justification(request: Request):
    """
    FastAPI dependency for support agents.
    Support agents must provide a justification header on every request
    that accesses PHI — enforced at the route level.

    Usage:
        @router.get("/patients/{id}")
        async def get_patient(
            ...,
            justification: str = Depends(require_justification)
        ):
    """
    justification = request.headers.get("X-Access-Justification")
    if not justification:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="X-Access-Justification header is required for this operation"
        )
    return justification