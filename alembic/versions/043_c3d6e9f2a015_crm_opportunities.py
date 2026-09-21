"""CRM opportunities, stage history, and lead conversion FK.

Revision ID: c3d6e9f2a015
Revises: b2c5d8e3f014
Create Date: 2026-09-21 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "c3d6e9f2a015"
down_revision: str | None = "b2c5d8e3f014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "crm_opportunity_number_counters",
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
        sa.UniqueConstraint("tenant_id", name="uq_crm_opportunity_number_counters_tenant_id"),
    )
    op.create_index(
        "ix_crm_opportunity_number_counters_tenant_id",
        "crm_opportunity_number_counters",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "crm_opportunities",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("opportunity_number", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("customer_id", UUID, nullable=True),
        sa.Column("contact_id", UUID, nullable=True),
        sa.Column("pipeline_id", UUID, nullable=False),
        sa.Column("stage_id", UUID, nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("currency_id", UUID, nullable=True),
        sa.Column("probability", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column("lost_reason_id", UUID, nullable=True),
        sa.Column("owner_id", UUID, nullable=True),
        sa.Column("source_id", UUID, nullable=True),
        sa.Column("lead_id", UUID, nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
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
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["crm_leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lost_reason_id"], ["crm_lost_reasons.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pipeline_id"], ["crm_pipelines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_id"], ["crm_lead_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stage_id"], ["crm_pipeline_stages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crm_opportunities_tenant_id", "crm_opportunities", ["tenant_id"], unique=False)
    op.create_index(
        "uq_crm_opportunities_tenant_id_opportunity_number_active",
        "crm_opportunities",
        ["tenant_id", "opportunity_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_crm_opportunities_tenant_id_status",
        "crm_opportunities",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_crm_opportunities_tenant_id_pipeline_id",
        "crm_opportunities",
        ["tenant_id", "pipeline_id"],
        unique=False,
    )
    op.create_index(
        "ix_crm_opportunities_tenant_id_stage_id",
        "crm_opportunities",
        ["tenant_id", "stage_id"],
        unique=False,
    )
    op.create_index(
        "ix_crm_opportunities_tenant_id_owner_id",
        "crm_opportunities",
        ["tenant_id", "owner_id"],
        unique=False,
    )
    op.create_index(
        "ix_crm_opportunities_tenant_id_customer_id",
        "crm_opportunities",
        ["tenant_id", "customer_id"],
        unique=False,
    )

    op.create_table(
        "crm_opportunity_stage_history",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("opportunity_id", UUID, nullable=False),
        sa.Column("from_stage_id", UUID, nullable=True),
        sa.Column("to_stage_id", UUID, nullable=False),
        sa.Column("changed_by", UUID, nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["from_stage_id"], ["crm_pipeline_stages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["opportunity_id"], ["crm_opportunities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_stage_id"], ["crm_pipeline_stages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_crm_opportunity_stage_history_opportunity_id",
        "crm_opportunity_stage_history",
        ["opportunity_id"],
        unique=False,
    )
    op.create_index(
        "ix_crm_opportunity_stage_history_tenant_id",
        "crm_opportunity_stage_history",
        ["tenant_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_crm_leads_converted_opportunity_id",
        "crm_leads",
        "crm_opportunities",
        ["converted_opportunity_id"],
        ["id"],
        ondelete="SET NULL",
    )

    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    for (tenant_id,) in tenants:
        bind.execute(
            sa.text(
                """
                INSERT INTO crm_opportunity_number_counters (id, tenant_id, next_number)
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
    op.drop_constraint("fk_crm_leads_converted_opportunity_id", "crm_leads", type_="foreignkey")

    op.drop_index(
        "ix_crm_opportunity_stage_history_tenant_id",
        table_name="crm_opportunity_stage_history",
    )
    op.drop_index(
        "ix_crm_opportunity_stage_history_opportunity_id",
        table_name="crm_opportunity_stage_history",
    )
    op.drop_table("crm_opportunity_stage_history")

    op.drop_index("ix_crm_opportunities_tenant_id_customer_id", table_name="crm_opportunities")
    op.drop_index("ix_crm_opportunities_tenant_id_owner_id", table_name="crm_opportunities")
    op.drop_index("ix_crm_opportunities_tenant_id_stage_id", table_name="crm_opportunities")
    op.drop_index("ix_crm_opportunities_tenant_id_pipeline_id", table_name="crm_opportunities")
    op.drop_index("ix_crm_opportunities_tenant_id_status", table_name="crm_opportunities")
    op.drop_index(
        "uq_crm_opportunities_tenant_id_opportunity_number_active",
        table_name="crm_opportunities",
    )
    op.drop_index("ix_crm_opportunities_tenant_id", table_name="crm_opportunities")
    op.drop_table("crm_opportunities")

    op.drop_index(
        "ix_crm_opportunity_number_counters_tenant_id",
        table_name="crm_opportunity_number_counters",
    )
    op.drop_table("crm_opportunity_number_counters")
