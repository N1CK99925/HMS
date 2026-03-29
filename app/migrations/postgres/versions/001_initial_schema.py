# migrations/postgres/versions/0001_initial_schema.py
# The very first migration — creates all PostgreSQL tables from scratch.
#
# Every migration file has:
#   revision  — unique ID for this migration
#   down_revision — which migration comes before this one (None = first)
#   upgrade() — what to do when applying this migration
#   downgrade() — how to reverse it
#
# NEVER edit a migration file after it has been run on any server.
# If you need to change something, create a NEW migration file.

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# Alembic tracks migrations using these two values
revision = "0001"
down_revision = None        # This is the first migration — nothing before it
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Creates all tables in the correct order.
    Order matters because of foreign keys:
    charge_master must exist before billing_charge_lines references it.
    billing must exist before insurance_claims references it.
    """

    # ── charge_master ──────────────────────────────────────────────────────
    # Created first because billing_charge_lines has a FK to it
    op.create_table(
        "charge_master",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("service_code", sa.String(50), nullable=False),
        sa.Column("service_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR"),
        sa.Column("cpt_code", sa.String(20), nullable=True),
        sa.Column("icd_code", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    # Unique: service_code must be unique per tenant
    op.create_unique_constraint(
        "uq_charge_tenant_code",
        "charge_master",
        ["tenant_id", "service_code"]
    )
    # Index for active services per tenant
    op.create_index(
        "idx_charge_tenant_active",
        "charge_master",
        ["tenant_id", "is_active"]
    )

    # ── billing ────────────────────────────────────────────────────────────
    op.create_table(
        "billing",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("encounter_id", sa.String(), nullable=False),
        sa.Column("patient_id", sa.String(), nullable=False),
        sa.Column("subtotal", sa.Float(), server_default="0"),
        sa.Column("discount_amount", sa.Float(), server_default="0"),
        sa.Column("tax_amount", sa.Float(), server_default="0"),
        sa.Column("total_amount", sa.Float(), nullable=False),
        sa.Column("copay_amount", sa.Float(), server_default="0"),
        sa.Column("copay_collected", sa.Float(), server_default="0"),
        sa.Column("write_off_amount", sa.Float(), server_default="0"),
        sa.Column("write_off_reason", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft", "finalised", "partially_paid",
                "paid", "written_off", "cancelled",
                name="billingstatus"
            ),
            server_default="draft",
            nullable=False
        ),
        sa.Column("currency", sa.String(3), server_default="INR"),
        sa.Column("generated_by_staff_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_unique_constraint(
        "uq_billing_tenant_encounter",
        "billing",
        ["tenant_id", "encounter_id"]
    )
    op.create_index("idx_billing_tenant_patient", "billing", ["tenant_id", "patient_id"])
    op.create_index("idx_billing_tenant_status", "billing", ["tenant_id", "status"])

    # ── billing_charge_lines ───────────────────────────────────────────────
    # Line items on a bill — depends on both billing and charge_master
    op.create_table(
        "billing_charge_lines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column(
            "bill_id",
            UUID(as_uuid=True),
            sa.ForeignKey("billing.id"),   # FK to billing table
            nullable=False
        ),
        sa.Column(
            "charge_master_id",
            UUID(as_uuid=True),
            sa.ForeignKey("charge_master.id"),  # FK to charge_master
            nullable=True   # Nullable: some charges may be custom, not in master
        ),
        sa.Column("service_name", sa.String(255), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default="1"),
        sa.Column("line_total", sa.Float(), nullable=False),
    )
    op.create_index("idx_chargeline_bill", "billing_charge_lines", ["bill_id"])

    # ── insurance_claims ───────────────────────────────────────────────────
    op.create_table(
        "insurance_claims",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column(
            "bill_id",
            UUID(as_uuid=True),
            sa.ForeignKey("billing.id"),
            nullable=False
        ),
        sa.Column("payer_name", sa.String(255), nullable=False),
        sa.Column("payer_id", sa.String(100), nullable=True),
        sa.Column(
            "payer_tier",
            sa.Enum("primary", "secondary", "tertiary", name="payertier"),
            nullable=False
        ),
        sa.Column("member_id", sa.String(100), nullable=False),
        sa.Column("group_number", sa.String(100), nullable=True),
        sa.Column("billed_amount", sa.Float(), nullable=False),
        sa.Column("claimed_amount", sa.Float(), nullable=False),
        sa.Column("adjudicated_amount", sa.Float(), nullable=True),
        sa.Column("paid_amount", sa.Float(), nullable=True),
        sa.Column("denied_amount", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft", "submitted", "acknowledged",
                "adjudicated", "paid", "denied", "appealed", "write_off",
                name="claimstatus"
            ),
            server_default="draft",
            nullable=False
        ),
        sa.Column("denial_reason", sa.Text(), nullable=True),
        sa.Column("appeal_notes", sa.Text(), nullable=True),
        sa.Column("era_reference", sa.String(255), nullable=True),
        sa.Column("eob_reference", sa.String(255), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("adjudicated_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_unique_constraint(
        "uq_claim_bill_payer_tier",
        "insurance_claims",
        ["bill_id", "payer_tier"]
    )
    op.create_index(
        "idx_claim_tenant_payer_status",
        "insurance_claims",
        ["tenant_id", "payer_id", "status"]
    )
    op.create_index(
        "idx_claim_tenant_status_date",
        "insurance_claims",
        ["tenant_id", "status", "submitted_at"]
    )

    # ── audit_logs ─────────────────────────────────────────────────────────
    # Created last — it references no other table (intentionally)
    # The audit log must survive even if referenced records are soft-deleted
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("actor_role", sa.String(), nullable=False),
        sa.Column(
            "action",
            sa.Enum(
                "read", "create", "update", "soft_delete", "export", "print",
                name="auditaction"
            ),
            nullable=False
        ),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("prev_state_hash", sa.String(64), nullable=True),
        sa.Column("new_state_hash", sa.String(64), nullable=True),
        sa.Column("access_justification_code", sa.String(50), nullable=True),
        sa.Column("justification_notes", sa.Text(), nullable=True),
        sa.Column("accessed_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
    )
    # Critical query path Q7: compliance officer lookup by actor + date range
    op.create_index(
        "idx_audit_tenant_actor_date",
        "audit_logs",
        ["tenant_id", "actor_id", "accessed_at"]
    )
    op.create_index(
        "idx_audit_resource",
        "audit_logs",
        ["tenant_id", "resource_type", "resource_id"]
    )
    op.create_index("idx_audit_date", "audit_logs", ["accessed_at"])


def downgrade() -> None:
    """
    Reverses everything upgrade() did — in REVERSE ORDER.
    Tables with foreign keys must be dropped BEFORE the tables they reference.
    """
    # Drop indexes first, then tables
    op.drop_table("audit_logs")
    op.drop_table("insurance_claims")
    op.drop_table("billing_charge_lines")
    op.drop_table("billing")
    op.drop_table("charge_master")

    # Drop the custom Enum types PostgreSQL created
    op.execute("DROP TYPE IF EXISTS auditaction")
    op.execute("DROP TYPE IF EXISTS claimstatus")
    op.execute("DROP TYPE IF EXISTS payertier")
    op.execute("DROP TYPE IF EXISTS billingstatus")