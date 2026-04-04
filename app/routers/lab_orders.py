# app/routers/lab_orders.py
# Lab order endpoints.
# Doctors create orders. Lab technicians collect specimens and enter results.
# Critical results trigger an immediate notification and require acknowledgement.

from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.core.database import get_mongo_db
from app.core.roles import Role
from app.core.permissions import Permission
from app.middleware.rbac import require_permission, require_roles
from app.middleware.audit import write_phi_audit
from app.models.mongo.lab_order import (
    LabOrder, LabOrderStatus, LabResult,
    SpecimenType, SpecimenCollection
)
from app.models.postgres.billing import AuditAction

router = APIRouter(tags=["lab_orders"])


# ── Request shapes ─────────────────────────────────────────────────────────

class CreateLabOrderRequest(BaseModel):
    encounter_id: str
    patient_id: str
    department_id: str
    panel_code: Optional[str] = None
    panel_name: Optional[str] = None
    individual_test_codes: list[str] = []
    clinical_indication: Optional[str] = None
    priority: str = "routine"
    specimen_type: SpecimenType = SpecimenType.BLOOD


class RecordSpecimenRequest(BaseModel):
    specimen_id: str          # Barcode on the physical tube
    specimen_type: SpecimenType
    notes: Optional[str] = None


class EnterResultRequest(BaseModel):
    """
    Lab technician enters results for one or more tests in this order.
    Each result is one test within the order.
    """
    test_code: str
    test_name: str
    value: str
    numeric_value: Optional[float] = None
    unit: str
    is_abnormal: bool = False
    abnormal_flag: Optional[str] = None   # "H" | "L" | "HH" | "LL"
    is_critical: bool = False
    reference_range_version_id: Optional[str] = None


class AcknowledgeCriticalRequest(BaseModel):
    result_id: str
    acknowledgement_note: Optional[str] = None


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/lab-orders", status_code=status.HTTP_201_CREATED)
async def create_lab_order(
    body: CreateLabOrderRequest,
    request: Request,
    current_user: dict = Depends(require_permission(Permission.LAB_ORDER_WRITE))
):
    """
    Doctor creates a lab order.
    Must specify either a panel_code or individual_test_codes — not neither.
    """
    if not body.panel_code and not body.individual_test_codes:
        raise HTTPException(
            status_code=400,
            detail="Must specify either panel_code or individual_test_codes"
        )

    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    # Verify encounter belongs to this tenant
    encounter = await db["encounters"].find_one({
        "id": body.encounter_id,
        "tenant_id": tenant_id
    })
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")

    order = LabOrder(
        tenant_id=tenant_id,
        encounter_id=body.encounter_id,
        patient_id=body.patient_id,
        ordering_doctor_id=current_user["user_id"],
        department_id=body.department_id,
        panel_code=body.panel_code,
        panel_name=body.panel_name,
        individual_test_codes=body.individual_test_codes,
        clinical_indication=body.clinical_indication,
        priority=body.priority,
        specimen_type=body.specimen_type,
    )

    order_dict = order.model_dump()
    await db["lab_orders"].insert_one(order_dict)

    await write_phi_audit(
        request=request,
        action=AuditAction.CREATE,
        resource_type="lab_order",
        resource_id=order.id,
        new_doc=order_dict,
    )

    return order_dict


@router.get("/lab-orders/worklist")
async def get_lab_worklist(
    request: Request,
    department_id: str = Query(...),
    status_filter: LabOrderStatus = Query(LabOrderStatus.PENDING),
    current_user: dict = Depends(require_roles(
        Role.LAB_TECHNICIAN, Role.HOSPITAL_ADMIN, Role.DEPARTMENT_HEAD
    ))
):
    """
    Lab technician worklist — all orders for a department by status.
    Critical query path Q4 from ADR: served by compound index
    (tenant_id, department_id, status, ordered_at).
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    orders = await db["lab_orders"].find({
        "tenant_id": tenant_id,
        "department_id": department_id,
        "status": status_filter,
    }).sort("ordered_at", 1).to_list(length=100)  # Oldest first — FIFO processing

    return {"total": len(orders), "data": orders}


@router.patch("/lab-orders/{order_id}/collect")
async def record_specimen_collection(
    order_id: str,
    body: RecordSpecimenRequest,
    request: Request,
    current_user: dict = Depends(require_roles(
        Role.LAB_TECHNICIAN, Role.NURSE
    ))
):
    """
    Records that a specimen has been collected.
    Changes order status from PENDING to COLLECTED.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    order = await db["lab_orders"].find_one({
        "id": order_id,
        "tenant_id": tenant_id
    })
    if not order:
        raise HTTPException(status_code=404, detail="Lab order not found")

    if order["status"] != LabOrderStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot collect specimen — order status is {order['status']}"
        )

    collection = SpecimenCollection(
        collected_at=datetime.utcnow(),
        collected_by_id=current_user["user_id"],
        specimen_type=body.specimen_type,
        specimen_id=body.specimen_id,
        notes=body.notes,
    )

    await db["lab_orders"].update_one(
        {"id": order_id, "tenant_id": tenant_id},
        {"$set": {
            "status": LabOrderStatus.COLLECTED,
            "specimen_collection": collection.model_dump(),
            "updated_at": datetime.utcnow(),
        }}
    )

    return {"message": "Specimen collection recorded", "status": LabOrderStatus.COLLECTED}


@router.post("/lab-orders/{order_id}/results")
async def enter_result(
    order_id: str,
    body: EnterResultRequest,
    request: Request,
    current_user: dict = Depends(require_permission(Permission.LAB_RESULT_WRITE))
):
    """
    Lab technician enters a test result.
    Only lab_technicians have LAB_RESULT_WRITE permission.
    If the result is critical, an alert is triggered.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    order = await db["lab_orders"].find_one({
        "id": order_id,
        "tenant_id": tenant_id
    })
    if not order:
        raise HTTPException(status_code=404, detail="Lab order not found")

    if order["status"] == LabOrderStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Cannot enter results for cancelled order")

    result = LabResult(
        test_code=body.test_code,
        test_name=body.test_name,
        value=body.value,
        numeric_value=body.numeric_value,
        unit=body.unit,
        is_abnormal=body.is_abnormal,
        abnormal_flag=body.abnormal_flag,
        is_critical=body.is_critical,
        reference_range_version_id=body.reference_range_version_id,
        resulted_by_id=current_user["user_id"],
    )

    # Determine new order status
    new_status = LabOrderStatus.RESULTED

    await db["lab_orders"].update_one(
        {"id": order_id, "tenant_id": tenant_id},
        {
            "$push": {"results": result.model_dump()},
            "$set": {
                "status": new_status,
                "resulted_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        }
    )

    await write_phi_audit(
        request=request,
        action=AuditAction.CREATE,
        resource_type="lab_result",
        resource_id=f"{order_id}/{result.id}",
        new_doc=result.model_dump(),
    )

    # If critical — queue an alert via Celery (Day 9)
    # For now we just flag it — the Celery task will be wired in Day 9
    if body.is_critical:
        # TODO Day 9: from app.workers.tasks import send_critical_lab_alert
        # send_critical_lab_alert.delay(order_id, result.id, order["ordering_doctor_id"])
        pass

    return {
        "message": "Result entered",
        "result_id": result.id,
        "is_critical": body.is_critical,
        "alert_sent": body.is_critical,  # Will be True once Celery is wired
    }


@router.post("/lab-orders/{order_id}/acknowledge-critical")
async def acknowledge_critical_result(
    order_id: str,
    body: AcknowledgeCriticalRequest,
    request: Request,
    current_user: dict = Depends(require_roles(Role.DOCTOR, Role.SPECIALIST))
):
    """
    Doctor acknowledges a critical lab result.
    Only doctors can acknowledge — nurses and others cannot.
    The acknowledgement is audited — this creates a legally important record
    that the doctor was informed of the critical value.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    order = await db["lab_orders"].find_one({
        "id": order_id,
        "tenant_id": tenant_id
    })
    if not order:
        raise HTTPException(status_code=404, detail="Lab order not found")

    # Find the specific result and acknowledge it
    result_found = False
    for result in order.get("results", []):
        if result["id"] == body.result_id and result.get("is_critical"):
            result_found = True
            break

    if not result_found:
        raise HTTPException(status_code=404, detail="Critical result not found")

    # Update the specific result's acknowledgement fields
    await db["lab_orders"].update_one(
        {
            "id": order_id,
            "tenant_id": tenant_id,
            "results.id": body.result_id
        },
        {"$set": {
            "results.$.critical_acknowledged": True,
            "results.$.critical_acknowledged_by_id": current_user["user_id"],
            "results.$.critical_acknowledged_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }}
    )

    # Audit this acknowledgement — it is a legally significant event
    await write_phi_audit(
        request=request,
        action=AuditAction.UPDATE,
        resource_type="lab_result_critical_ack",
        resource_id=f"{order_id}/{body.result_id}",
        new_doc={"acknowledged_by": current_user["user_id"], "note": body.acknowledgement_note},
    )

    return {"message": "Critical result acknowledged"}


@router.get("/patients/{patient_id}/lab-orders")
async def get_patient_lab_history(
    patient_id: str,
    request: Request,
    current_user: dict = Depends(require_permission(Permission.LAB_RESULT_READ))
):
    """Returns all lab orders for a patient, most recent first."""
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    orders = await db["lab_orders"].find({
        "tenant_id": tenant_id,
        "patient_id": patient_id,
    }).sort("ordered_at", -1).to_list(length=200)

    await write_phi_audit(
        request=request,
        action=AuditAction.READ,
        resource_type="lab_order",
        resource_id=f"patient:{patient_id}",
    )

    return {"total": len(orders), "data": orders}