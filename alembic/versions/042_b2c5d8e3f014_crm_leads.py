"""CRM leads and lead number counters.

Revision ID: b2c5d8e3f014
Revises: a1f4e8c2b901
Create Date: 2026-09-21 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "b2c5d8e3f014"
down_revision: str | None = "a1f4e8c2b901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "crm_lead_number_counters",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("next_number", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_crm_lead_number_counters_tenant_id"),
    )
    op.create_index(
        "ix_crm_lead_number_counters_tenant_id",
        "crm_lead_number_counters",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "crm_leads",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("lead_number", sa.String(length=40), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=True),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("title", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=30), server_default=sa.text("'NEW'"), nullable=False),
        sa.Column("rating", sa.String(length=20), nullable=True),
        sa.Column("source_id", UUID, nullable=True),
        sa.Column("owner_id", UUID, nullable=True),
        sa.Column("estimated_value", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("currency_id", UUID, nullable=True),
        sa.Column("notes", sa.String(length=4000), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("converted_customer_id", UUID, nullable=True),
        sa.Column("converted_contact_id", UUID, nullable=True),
        sa.Column("converted_opportunity_id", UUID, nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["converted_contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["converted_customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["crm_lead_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crm_leads_tenant_id", "crm_leads", ["tenant_id"], unique=False)
    op.create_index(
        "uq_crm_leads_tenant_id_lead_number_active",
        "crm_leads",
        ["tenant_id", "lead_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_crm_leads_tenant_id_status",
        "crm_leads",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_crm_leads_tenant_id_owner_id",
        "crm_leads",
        ["tenant_id", "owner_id"],
        unique=False,
    )
    op.create_index(
        "ix_crm_leads_tenant_id_source_id",
        "crm_leads",
        ["tenant_id", "source_id"],
        unique=False,
    )

    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    for (tenant_id,) in tenants:
        bind.execute(
            sa.text(
                """
                INSERT INTO crm_lead_number_counters (id, tenant_id, next_number)
                VALUES (gen_random_uuid(), :tenant_id, 1)
                ON CONFLICT (tenant_id) DO NOTHING
                """
            ),
            {"tenant_id": tenant_id},
        )

    _backfill_catalog_permissions()


def _backfill_catalog_permissions() -> None:
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    catalog = parsed_catalog_permissions()

    for (tenant_id,) in tenants:
        existing = bind.execute(
            sa.text(
                "SELECT module, resource, action FROM permissions WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).fetchall()
        existing_keys = {(row.module, row.resource, row.action) for row in existing}
        for parsed in catalog:
            key = (parsed.module, parsed.resource, parsed.action)
            if key in existing_keys:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO permissions (tenant_id, module, resource, action)
                    VALUES (:tenant_id, :module, :resource, :action)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "module": parsed.module,
                    "resource": parsed.resource,
                    "action": parsed.action,
                },
            )

        admin = bind.execute(
            sa.text(
                """
                SELECT id FROM roles
                WHERE tenant_id = :tenant_id
                  AND is_system_role = true
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if admin is not None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO role_permissions (tenant_id, role_id, permission_id)
                    SELECT :tenant_id, :role_id, p.id
                    FROM permissions p
                    WHERE p.tenant_id = :tenant_id
                      AND NOT EXISTS (
                        SELECT 1
                        FROM role_permissions rp
                        WHERE rp.tenant_id = :tenant_id
                          AND rp.role_id = :role_id
                          AND rp.permission_id = p.id
                      )
                    """
                ),
                {"tenant_id": tenant_id, "role_id": admin.id},
            )


def downgrade() -> None:
    op.drop_index("ix_crm_leads_tenant_id_source_id", table_name="crm_leads")
    op.drop_index("ix_crm_leads_tenant_id_owner_id", table_name="crm_leads")
    op.drop_index("ix_crm_leads_tenant_id_status", table_name="crm_leads")
    op.drop_index("uq_crm_leads_tenant_id_lead_number_active", table_name="crm_leads")
    op.drop_index("ix_crm_leads_tenant_id", table_name="crm_leads")
    op.drop_table("crm_leads")

    op.drop_index("ix_crm_lead_number_counters_tenant_id", table_name="crm_lead_number_counters")
    op.drop_table("crm_lead_number_counters")
