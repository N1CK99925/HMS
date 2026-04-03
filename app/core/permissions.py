# app/core/permissions.py

from app.core.roles import Role


class Permission:
    """
    Every resource:action pair defined as a typed constant.
    Equivalent to Spring's GrantedAuthority strings — but type-safe.
    """
    # Patient
    PATIENT_READ                = "patient:read"
    PATIENT_WRITE               = "patient:write"
    PATIENT_DEMOGRAPHICS_WRITE  = "patient_demographics:write"

    # Encounter
    ENCOUNTER_READ              = "encounter:read"
    ENCOUNTER_WRITE             = "encounter:write"

    # Clinical notes
    CLINICAL_NOTE_READ          = "clinical_note:read"
    CLINICAL_NOTE_WRITE         = "clinical_note:write"
    NURSING_NOTE_WRITE          = "nursing_note:write"

    # Prescriptions
    PRESCRIPTION_READ           = "prescription:read"
    PRESCRIPTION_WRITE          = "prescription:write"
    DISPENSE_STATUS_WRITE       = "dispense_status:write"

    # Lab
    LAB_ORDER_READ              = "lab_order:read"
    LAB_ORDER_WRITE             = "lab_order:write"
    LAB_RESULT_READ             = "lab_result:read"
    LAB_RESULT_WRITE            = "lab_result:write"

    # Imaging
    IMAGING_READ                = "imaging:read"
    IMAGING_ORDER_WRITE         = "imaging_order:write"
    IMAGING_REPORT_WRITE        = "imaging_report:write"

    # Vitals
    VITALS_READ                 = "vitals:read"
    VITALS_WRITE                = "vitals:write"
    MEDICATION_ADMIN_WRITE      = "medication_admin:write"

    # Appointments
    APPOINTMENT_READ            = "appointment:read"
    APPOINTMENT_WRITE           = "appointment:write"

    # Billing
    BILLING_READ                = "billing:read"
    BILLING_WRITE               = "billing:write"
    CHARGE_MASTER_READ          = "charge_master:read"
    CHARGE_MASTER_WRITE         = "charge_master:write"
    INSURANCE_CLAIM_READ        = "insurance_claim:read"
    INSURANCE_CLAIM_WRITE       = "insurance_claim:write"
    PAYMENT_READ                = "payment:read"
    PAYMENT_WRITE               = "payment:write"

    # Staff and HR
    STAFF_READ                  = "staff:read"
    STAFF_WRITE                 = "staff:write"
    CREDENTIAL_READ             = "credential:read"
    CREDENTIAL_WRITE            = "credential:write"
    LEAVE_REQUEST_READ          = "leave_request:read"
    LEAVE_REQUEST_WRITE         = "leave_request:write"

    # Org
    DEPARTMENT_READ             = "department:read"
    DEPARTMENT_WRITE            = "department:write"
    ROLE_READ                   = "role:read"
    ROLE_WRITE                  = "role:write"

    # Platform / config
    TENANT_READ                 = "tenant:read"
    TENANT_WRITE                = "tenant:write"
    TENANT_IMPERSONATE          = "tenant:impersonate"
    TENANT_FEATURE_FLAGS_WRITE  = "tenant:feature_flags:write"
    SITE_READ                   = "site:read"
    SITE_WRITE                  = "site:write"
    API_KEY_READ                = "api_key:read"
    API_KEY_WRITE               = "api_key:write"
    INTEGRATION_READ            = "integration:read"
    INTEGRATION_WRITE           = "integration:write"

    # Compliance
    AUDIT_LOG_READ              = "audit_log:read"

    # Referrals and consent
    REFERRAL_READ               = "referral:read"
    REFERRAL_WRITE              = "referral:write"
    CAREGIVER_CONSENT_WRITE     = "caregiver_consent:write"

    # Drug master
    DRUG_MASTER_READ            = "drug_master:read"

    # Analytics
    ANALYTICS_READ              = "analytics:read"


# ── Role → Permission mapping ──────────────────────────────────────────────
# This is the Python equivalent of Spring's SecurityConfig + @PreAuthorize.
# One place. Every role. Every permission. Version controlled in Git.
# Change a permission here and it takes effect everywhere immediately.

ROLE_PERMISSIONS: dict[Role, set[str]] = {

    # ── Platform ───────────────────────────────────────────────────────────

    Role.SUPER_ADMIN: {
        Permission.TENANT_READ, Permission.TENANT_WRITE,
        Permission.TENANT_IMPERSONATE,
        Permission.TENANT_FEATURE_FLAGS_WRITE,
        Permission.PATIENT_READ, Permission.PATIENT_WRITE,
        Permission.ENCOUNTER_READ,
        Permission.CLINICAL_NOTE_READ,
        Permission.PRESCRIPTION_READ,
        Permission.LAB_RESULT_READ,
        Permission.IMAGING_READ,
        Permission.BILLING_READ, Permission.BILLING_WRITE,
        Permission.STAFF_READ, Permission.STAFF_WRITE,
        Permission.DEPARTMENT_READ, Permission.DEPARTMENT_WRITE,
        Permission.ROLE_READ, Permission.ROLE_WRITE,
        Permission.AUDIT_LOG_READ,
        Permission.API_KEY_READ, Permission.API_KEY_WRITE,
        Permission.INTEGRATION_READ, Permission.INTEGRATION_WRITE,
        Permission.SITE_READ, Permission.SITE_WRITE,
    },

    Role.SUPPORT_AGENT: {
        Permission.TENANT_READ,
        Permission.PATIENT_READ,
        Permission.ENCOUNTER_READ,
        Permission.CLINICAL_NOTE_READ,
        Permission.PRESCRIPTION_READ,
        Permission.LAB_RESULT_READ,
        Permission.BILLING_READ,
        Permission.STAFF_READ,
        Permission.AUDIT_LOG_READ,
    },

    Role.COMPLIANCE_OFFICER: {
        Permission.AUDIT_LOG_READ,
        Permission.TENANT_READ,
        Permission.PATIENT_READ,
        Permission.STAFF_READ,
    },

    # ── Tenant ─────────────────────────────────────────────────────────────

    Role.HOSPITAL_ADMIN: {
        Permission.PATIENT_READ, Permission.PATIENT_WRITE,
        Permission.ENCOUNTER_READ,
        Permission.CLINICAL_NOTE_READ,
        Permission.PRESCRIPTION_READ,
        Permission.LAB_RESULT_READ,
        Permission.IMAGING_READ,
        Permission.BILLING_READ, Permission.BILLING_WRITE,
        Permission.CHARGE_MASTER_READ, Permission.CHARGE_MASTER_WRITE,
        Permission.INSURANCE_CLAIM_READ, Permission.INSURANCE_CLAIM_WRITE,
        Permission.STAFF_READ, Permission.STAFF_WRITE,
        Permission.DEPARTMENT_READ, Permission.DEPARTMENT_WRITE,
        Permission.ROLE_READ, Permission.ROLE_WRITE,
        Permission.CREDENTIAL_READ, Permission.CREDENTIAL_WRITE,
        Permission.APPOINTMENT_READ, Permission.APPOINTMENT_WRITE,
        Permission.SITE_READ, Permission.SITE_WRITE,
        Permission.API_KEY_READ, Permission.API_KEY_WRITE,
        Permission.INTEGRATION_READ,
        Permission.AUDIT_LOG_READ,
    },

    Role.DEPARTMENT_HEAD: {
        Permission.PATIENT_READ,
        Permission.ENCOUNTER_READ,
        Permission.CLINICAL_NOTE_READ,
        Permission.STAFF_READ, Permission.STAFF_WRITE,
        Permission.DEPARTMENT_READ,
        Permission.LEAVE_REQUEST_READ, Permission.LEAVE_REQUEST_WRITE,
        Permission.ANALYTICS_READ,
        Permission.APPOINTMENT_READ,
    },

    Role.HR_MANAGER: {
        Permission.STAFF_READ, Permission.STAFF_WRITE,
        Permission.CREDENTIAL_READ, Permission.CREDENTIAL_WRITE,
        Permission.LEAVE_REQUEST_READ, Permission.LEAVE_REQUEST_WRITE,
        Permission.DEPARTMENT_READ,
    },

    Role.FINANCE_MANAGER: {
        Permission.BILLING_READ, Permission.BILLING_WRITE,
        Permission.CHARGE_MASTER_READ, Permission.CHARGE_MASTER_WRITE,
        Permission.INSURANCE_CLAIM_READ, Permission.INSURANCE_CLAIM_WRITE,
        Permission.PAYMENT_READ, Permission.PAYMENT_WRITE,
        Permission.PATIENT_READ,
    },

    Role.IT_ADMINISTRATOR: {
        Permission.SITE_READ, Permission.SITE_WRITE,
        Permission.API_KEY_READ, Permission.API_KEY_WRITE,
        Permission.INTEGRATION_READ, Permission.INTEGRATION_WRITE,
        Permission.STAFF_READ,
    },

    # ── Clinical ───────────────────────────────────────────────────────────

    Role.DOCTOR: {
        Permission.PATIENT_READ, Permission.PATIENT_WRITE,
        Permission.ENCOUNTER_READ, Permission.ENCOUNTER_WRITE,
        Permission.CLINICAL_NOTE_READ, Permission.CLINICAL_NOTE_WRITE,
        Permission.PRESCRIPTION_READ, Permission.PRESCRIPTION_WRITE,
        Permission.LAB_ORDER_READ, Permission.LAB_ORDER_WRITE,
        Permission.LAB_RESULT_READ,
        Permission.IMAGING_READ, Permission.IMAGING_ORDER_WRITE,
        Permission.APPOINTMENT_READ, Permission.APPOINTMENT_WRITE,
        Permission.REFERRAL_READ, Permission.REFERRAL_WRITE,
        Permission.VITALS_READ,
    },

    Role.SPECIALIST: {
        # Same as doctor but referral-gated.
        # The permission existing here is necessary but not sufficient —
        # the referral check is enforced separately in the route middleware.
        Permission.PATIENT_READ,
        Permission.ENCOUNTER_READ,
        Permission.CLINICAL_NOTE_READ, Permission.CLINICAL_NOTE_WRITE,
        Permission.PRESCRIPTION_READ, Permission.PRESCRIPTION_WRITE,
        Permission.LAB_ORDER_READ, Permission.LAB_RESULT_READ,
        Permission.IMAGING_READ,
        Permission.REFERRAL_READ,
    },

    Role.NURSE: {
        Permission.PATIENT_READ,
        Permission.ENCOUNTER_READ,
        Permission.CLINICAL_NOTE_READ,
        Permission.NURSING_NOTE_WRITE,
        Permission.VITALS_READ, Permission.VITALS_WRITE,
        Permission.MEDICATION_ADMIN_WRITE,
        Permission.LAB_RESULT_READ,
        Permission.PRESCRIPTION_READ,
        Permission.APPOINTMENT_READ,
    },

    Role.PHARMACIST: {
        Permission.PRESCRIPTION_READ,
        Permission.DISPENSE_STATUS_WRITE,
        Permission.PATIENT_READ,
        Permission.DRUG_MASTER_READ,
    },

    Role.LAB_TECHNICIAN: {
        Permission.LAB_ORDER_READ,
        Permission.LAB_RESULT_WRITE,
        Permission.PATIENT_READ,
    },

    Role.RADIOLOGIST: {
        Permission.IMAGING_READ,
        Permission.IMAGING_REPORT_WRITE,
        Permission.PATIENT_READ,
    },

    Role.RECEPTIONIST: {
        Permission.PATIENT_READ,
        Permission.PATIENT_DEMOGRAPHICS_WRITE,
        Permission.APPOINTMENT_READ, Permission.APPOINTMENT_WRITE,
        Permission.ENCOUNTER_READ, Permission.ENCOUNTER_WRITE,
    },

    Role.BILLING_CODER: {
        Permission.ENCOUNTER_READ,
        Permission.PATIENT_READ,
        Permission.BILLING_READ, Permission.BILLING_WRITE,
        Permission.CHARGE_MASTER_READ,
        # Explicitly NO clinical_note:read — free text is off limits
    },

    # ── Patient ────────────────────────────────────────────────────────────

    Role.PATIENT: {
        Permission.PATIENT_READ,
        Permission.APPOINTMENT_READ, Permission.APPOINTMENT_WRITE,
        Permission.PRESCRIPTION_READ,
        Permission.LAB_RESULT_READ,
        Permission.CLINICAL_NOTE_READ,
        Permission.CAREGIVER_CONSENT_WRITE,
    },

    Role.CAREGIVER: {
        Permission.PATIENT_READ,
        Permission.APPOINTMENT_READ, Permission.APPOINTMENT_WRITE,
        Permission.PRESCRIPTION_READ,
        Permission.LAB_RESULT_READ,
        Permission.CLINICAL_NOTE_READ,
    },
}


def get_permissions_for_role(role: Role) -> set[str]:
    """Returns the permission set for a single role."""
    return ROLE_PERMISSIONS.get(role, set())


def get_permissions_for_roles(roles: list[Role]) -> set[str]:
    """
    Returns the merged permission set for multiple roles.
    Additive model — union of all roles' permissions.
    If a user is both NURSE and DEPARTMENT_HEAD they get both sets combined.
    """
    all_permissions: set[str] = set()
    for role in roles:
        all_permissions.update(get_permissions_for_role(role))
    return all_permissions