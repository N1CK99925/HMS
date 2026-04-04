# app/routers/imaging_studies.py
# Imaging study endpoints.
# Doctors order scans. Radiologists write reports.
# DICOM files live on Orthanc PACS — we only manage metadata here.

from fastapi import APIRouter, HTTPException, status, Request, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.core.database import get_mongo_db
from app.core.roles import Role
from app.core.permissions import Permission
from app.middleware.rbac import require_permission, require_roles
from app.middleware.audit import write_phi_audit
from app.models.mongo.imaging_study import (
    ImagingStudy, ImagingModality, ReportStatus,
    RadiologyReport, DicomHierarchy
)
from app.models.postgres.billing import AuditAction

router = APIRouter(tags=["imaging"])


# ── Request shapes ─────────────────────────────────────────────────────────

class CreateImagingOrderRequest(BaseModel):
    encounter_id: str
    patient_id: str
    modality: ImagingModality
    body_part: str
    clinical_indication: str
    priority: str = "routine"
    is_stat: bool = False


class AssignRadiologistRequest(BaseModel):
    radiologist_id: str


class LinkPacsRequest(BaseModel):
    """Called by PACS integration after the study is performed."""
    pacs_url: str
    wado_uri: str
    study_instance_uid: str
    series_count: int
    instance_count: int


class SubmitReportRequest(BaseModel):
    findings: str
    impression: str
    recommendation: Optional[str] = None
    is_final: bool = False     # False = preliminary, True = final signed report


class AddendumReportRequest(BaseModel):
    findings: str
    impression: str
    recommendation: Optional[str] = None
    addendum_reason: str        # Required — why is this addendum needed?


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/imaging-studies", status_code=status.HTTP_201_CREATED)
async def create_imaging_order(
    body: CreateImagingOrderRequest,
    request: Request,
    current_user: dict = Depends(require_permission(Permission.IMAGING_ORDER_WRITE))
):
    """
    Doctor orders an imaging study.
    The PACS URL is empty at this point — it gets filled in after the scan.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    encounter = await db["encounters"].find_one({
        "id": body.encounter_id,
        "tenant_id": tenant_id
    })
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")

    study = ImagingStudy(
        tenant_id=tenant_id,
        encounter_id=body.encounter_id,
        patient_id=body.patient_id,
        ordering_doctor_id=current_user["user_id"],
        modality=body.modality,
        body_part=body.body_part,
        clinical_indication=body.clinical_indication,
        priority=body.priority,
        is_stat=body.is_stat,
    )

    study_dict = study.model_dump()
    await db["imaging_studies"].insert_one(study_dict)

    await write_phi_audit(
        request=request,
        action=AuditAction.CREATE,
        resource_type="imaging_study",
        resource_id=study.id,
        new_doc=study_dict,
    )

    return study_dict


@router.patch("/imaging-studies/{study_id}/assign-radiologist")
async def assign_radiologist(
    study_id: str,
    body: AssignRadiologistRequest,
    request: Request,
    current_user: dict = Depends(require_roles(
        Role.HOSPITAL_ADMIN, Role.DEPARTMENT_HEAD
    ))
):
    """Assigns a radiologist to read and report on this study."""
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    study = await db["imaging_studies"].find_one({
        "id": study_id, "tenant_id": tenant_id
    })
    if not study:
        raise HTTPException(status_code=404, detail="Imaging study not found")

    await db["imaging_studies"].update_one(
        {"id": study_id, "tenant_id": tenant_id},
        {"$set": {
            "radiologist_id": body.radiologist_id,
            "updated_at": datetime.utcnow()
        }}
    )
    return {"message": "Radiologist assigned"}


@router.patch("/imaging-studies/{study_id}/link-pacs")
async def link_pacs_study(
    study_id: str,
    body: LinkPacsRequest,
    request: Request,
    current_user: dict = Depends(require_roles(
        Role.IT_ADMINISTRATOR, Role.HOSPITAL_ADMIN
    ))
):
    """
    Called by the PACS integration after the scan is performed.
    Links the DICOM metadata (PACS URL, WADO-URI, hierarchy) to the order.
    This is how the PACS server and HMS stay in sync.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    hierarchy = DicomHierarchy(
        study_instance_uid=body.study_instance_uid,
        series_count=body.series_count,
        instance_count=body.instance_count,
    )

    await db["imaging_studies"].update_one(
        {"id": study_id, "tenant_id": tenant_id},
        {"$set": {
            "pacs_url": body.pacs_url,
            "wado_uri": body.wado_uri,
            "dicom_hierarchy": hierarchy.model_dump(),
            "performed_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }}
    )
    return {"message": "PACS study linked"}


@router.post("/imaging-studies/{study_id}/report")
async def submit_report(
    study_id: str,
    body: SubmitReportRequest,
    request: Request,
    current_user: dict = Depends(require_permission(Permission.IMAGING_REPORT_WRITE))
):
    """
    Radiologist submits a report for an imaging study.
    is_final=False → preliminary report (can be updated)
    is_final=True  → final signed report (immutable — use addendum for corrections)
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    study = await db["imaging_studies"].find_one({
        "id": study_id, "tenant_id": tenant_id
    })
    if not study:
        raise HTTPException(status_code=404, detail="Imaging study not found")

    # Block if there's already a final report — use addendum instead
    if study.get("final_report"):
        raise HTTPException(
            status_code=400,
            detail="Final report already exists. Create an addendum instead."
        )

    report = RadiologyReport(
        findings=body.findings,
        impression=body.impression,
        recommendation=body.recommendation,
        reported_by_id=current_user["user_id"],
        status=ReportStatus.FINAL if body.is_final else ReportStatus.PRELIMINARY,
    )

    update_field = "final_report" if body.is_final else "preliminary_report"
    new_status   = ReportStatus.FINAL if body.is_final else ReportStatus.PRELIMINARY

    await db["imaging_studies"].update_one(
        {"id": study_id, "tenant_id": tenant_id},
        {"$set": {
            update_field: report.model_dump(),
            "report_status": new_status,
            "reported_at": datetime.utcnow() if body.is_final else None,
            "updated_at": datetime.utcnow(),
        }}
    )

    await write_phi_audit(
        request=request,
        action=AuditAction.CREATE,
        resource_type="imaging_report",
        resource_id=study_id,
        new_doc=report.model_dump(),
    )

    return {"message": f"{'Final' if body.is_final else 'Preliminary'} report submitted"}


@router.post("/imaging-studies/{study_id}/addendum")
async def submit_addendum(
    study_id: str,
    body: AddendumReportRequest,
    request: Request,
    current_user: dict = Depends(require_permission(Permission.IMAGING_REPORT_WRITE))
):
    """
    Adds an addendum to a final report.
    The original final report is never modified — addendum is appended.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    study = await db["imaging_studies"].find_one({
        "id": study_id, "tenant_id": tenant_id
    })
    if not study:
        raise HTTPException(status_code=404, detail="Imaging study not found")

    if not study.get("final_report"):
        raise HTTPException(
            status_code=400,
            detail="No final report exists yet — submit the final report first"
        )

    addendum = RadiologyReport(
        findings=body.findings,
        impression=body.impression,
        recommendation=body.recommendation,
        reported_by_id=current_user["user_id"],
        status=ReportStatus.ADDENDUM,
        addendum_reason=body.addendum_reason,
    )

    await db["imaging_studies"].update_one(
        {"id": study_id, "tenant_id": tenant_id},
        {
            "$push": {"addendum_reports": addendum.model_dump()},
            "$set": {
                "report_status": ReportStatus.ADDENDUM,
                "updated_at": datetime.utcnow()
            }
        }
    )

    return {"message": "Addendum submitted"}


@router.get("/imaging-studies/worklist")
async def get_radiologist_worklist(
    request: Request,
    current_user: dict = Depends(require_roles(
        Role.RADIOLOGIST, Role.HOSPITAL_ADMIN
    ))
):
    """
    Radiologist worklist — all studies assigned to this radiologist
    that don't yet have a final report.
    STAT studies appear first.
    """
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    studies = await db["imaging_studies"].find({
        "tenant_id": tenant_id,
        "radiologist_id": current_user["user_id"],
        "report_status": {"$ne": ReportStatus.FINAL},
    }).sort([("is_stat", -1), ("ordered_at", 1)]).to_list(length=100)

    return {"total": len(studies), "data": studies}


@router.get("/patients/{patient_id}/imaging")
async def get_patient_imaging_history(
    patient_id: str,
    request: Request,
    current_user: dict = Depends(require_permission(Permission.IMAGING_READ))
):
    """Returns all imaging studies for a patient."""
    db = get_mongo_db()
    tenant_id = request.state.tenant_id

    studies = await db["imaging_studies"].find({
        "tenant_id": tenant_id,
        "patient_id": patient_id,
    }).sort("ordered_at", -1).to_list(length=200)

    await write_phi_audit(
        request=request,
        action=AuditAction.READ,
        resource_type="imaging_study",
        resource_id=f"patient:{patient_id}",
    )

    return {"total": len(studies), "data": studies}