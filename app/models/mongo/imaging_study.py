# app/models/mongo/imaging_study.py
# Imaging studies are X-rays, MRIs, CT scans, ultrasounds etc.
#
# CRITICAL DESIGN RULE: We store ONLY metadata here.
# The actual DICOM binary files live on the Orthanc PACS server.
# We store the PACS URL reference so DICOM viewers can fetch the files
# directly via WADO-URI protocol.
#
# Why not store DICOM files here?
# 1. DICOM files are very large (50MB–2GB per study)
# 2. Radiology viewers (OHIF, Cornerstone) expect WADO-URI — not S3 URLs
# 3. PACS servers have specialised compression and streaming for DICOM
# 4. Regulatory requirements for imaging data differ from clinical text

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum
import uuid


class ImagingModality(str, Enum):
    """The type of imaging equipment used."""
    CR  = "CR"    # Computed Radiography (standard X-ray)
    CT  = "CT"    # Computed Tomography
    MR  = "MR"    # Magnetic Resonance Imaging
    US  = "US"    # Ultrasound
    NM  = "NM"    # Nuclear Medicine
    PT  = "PT"    # Positron Emission Tomography
    DX  = "DX"    # Digital X-ray
    MG  = "MG"    # Mammography
    ECG = "ECG"   # Electrocardiography


class ReportStatus(str, Enum):
    PENDING      = "pending"       # No report yet
    PRELIMINARY  = "preliminary"   # Draft report by radiologist
    FINAL        = "final"         # Signed final report
    ADDENDUM     = "addendum"      # Correction to a final report


class DicomHierarchy(BaseModel):
    """
    DICOM organises images in a Study → Series → Instance hierarchy.
    Study: one imaging session (e.g. chest X-ray on 2024-01-15)
    Series: one set of images within a session (e.g. AP view, lateral view)
    Instance: one individual image/frame
    We store counts only — the actual files are on the PACS server.
    """
    study_instance_uid: str     # Globally unique DICOM study ID
    series_count: int = 0       # How many series in this study
    instance_count: int = 0     # How many images total
    # Per-series metadata
    series: list[dict] = Field(default_factory=list)
    # Each series dict: {series_uid, modality, description, instance_count}


class RadiologyReport(BaseModel):
    """
    The written report by the radiologist.
    Structured as findings + impression + recommendation —
    the international standard for radiology reporting.

    Findings: what the radiologist sees ("There is a 2cm opacity in the right lower lobe")
    Impression: clinical interpretation ("Consistent with community-acquired pneumonia")
    Recommendation: what to do next ("Follow-up CXR in 4-6 weeks")
    """
    findings: str
    impression: str
    recommendation: Optional[str] = None

    # Authorship
    reported_by_id: str         # Radiologist staff ID
    reported_at: datetime = Field(default_factory=datetime.utcnow)

    # Report status
    status: ReportStatus = ReportStatus.PRELIMINARY

    # Addendum support — same pattern as clinical notes
    # If this is an addendum, addendum_reason explains why
    addendum_reason: Optional[str] = None
    original_report_id: Optional[str] = None


class ImagingStudy(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ── Tenant isolation — MANDATORY ──
    tenant_id: str

    # ── Core references ───────────────────────────────────────────────────
    encounter_id: str
    patient_id: str              # Denormalized for worklist queries
    ordering_doctor_id: str
    radiologist_id: Optional[str] = None  # Assigned after order is created

    # ── What was ordered ──────────────────────────────────────────────────
    modality: ImagingModality
    body_part: str               # e.g. "CHEST", "BRAIN", "ABDOMEN"
    clinical_indication: str     # Why was this scan ordered?
    priority: str = "routine"    # "routine" | "urgent" | "stat"

    # ── PACS integration ──────────────────────────────────────────────────
    # This is the link to the actual DICOM files on the Orthanc PACS server.
    # WADO-URI format: https://pacs.hospital.com/wado?studyUID=1.2.840...
    pacs_url: Optional[str] = None
    wado_uri: Optional[str] = None      # WADO-URI for DICOM viewers
    dicom_hierarchy: Optional[DicomHierarchy] = None

    # ── Report ────────────────────────────────────────────────────────────
    # Reports are embedded — they always belong to one study
    # preliminary_report: drafted by radiologist, not yet final
    # final_report: signed, immutable (corrections go in addendum)
    preliminary_report: Optional[RadiologyReport] = None
    final_report: Optional[RadiologyReport] = None
    addendum_reports: list[RadiologyReport] = Field(default_factory=list)

    # ── Status ────────────────────────────────────────────────────────────
    report_status: ReportStatus = ReportStatus.PENDING
    is_stat: bool = False        # Urgent — needs radiologist attention immediately

    # ── Timestamps ────────────────────────────────────────────────────────
    ordered_at: datetime = Field(default_factory=datetime.utcnow)
    performed_at: Optional[datetime] = None   # When the scan actually happened
    reported_at: Optional[datetime] = None    # When the final report was signed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


IMAGING_INDEXES = [
    # Radiologist worklist — "all pending studies assigned to me"
    {
        "key": [("tenant_id", 1), ("radiologist_id", 1), ("report_status", 1)],
        "name": "idx_imaging_tenant_radiologist_status"
    },
    # All imaging for an encounter
    {
        "key": [("tenant_id", 1), ("encounter_id", 1)],
        "name": "idx_imaging_tenant_encounter"
    },
    # All imaging for a patient (history)
    {
        "key": [("tenant_id", 1), ("patient_id", 1), ("ordered_at", -1)],
        "name": "idx_imaging_tenant_patient_date"
    },
    # STAT studies — need urgent attention
    {
        "key": [("tenant_id", 1), ("is_stat", 1), ("report_status", 1)],
        "name": "idx_imaging_tenant_stat_status"
    },
]

COLLECTION_NAME = "imaging_studies"