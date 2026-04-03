

from enum import Enum


class Role(str, Enum):

    SUPER_ADMIN         = "super_admin"
    SUPPORT_AGENT       = "support_agent"
    COMPLIANCE_OFFICER  = "compliance_officer"

    HOSPITAL_ADMIN      = "hospital_admin"
    DEPARTMENT_HEAD     = "department_head"
    HR_MANAGER          = "hr_manager"
    FINANCE_MANAGER     = "finance_manager"
    IT_ADMINISTRATOR    = "it_administrator"

    DOCTOR              = "doctor"
    SPECIALIST          = "specialist"
    NURSE               = "nurse"
    PHARMACIST          = "pharmacist"
    LAB_TECHNICIAN      = "lab_technician"
    RADIOLOGIST         = "radiologist"
    RECEPTIONIST        = "receptionist"
    BILLING_CODER       = "billing_coder"


    PATIENT             = "patient"
    CAREGIVER           = "caregiver"