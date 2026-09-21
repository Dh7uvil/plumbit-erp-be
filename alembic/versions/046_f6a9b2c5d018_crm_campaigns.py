"""CRM campaigns and member attribution.

Revision ID: f6a9b2c5d018
Revises: e5f8a1b4c017
Create Date: 2026-09-21 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "f6a9b2c5d018"
down_revision: str | None = "e5f8a1b4c017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "crm_campaigns",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("campaign_type", sa.String(length=30), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'PLANNED'"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("budgeted_cost", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("actual_cost", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("expected_revenue", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("owner_id", UUID, nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crm_campaigns_tenant_id", "crm_campaigns", ["tenant_id"], unique=False)
    op.create_index(
        "uq_crm_campaigns_tenant_id_name_active",
        "crm_campaigns",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_crm_campaigns_tenant_id_status",
        "crm_campaigns",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_crm_campaigns_tenant_id_owner_id",
        "crm_campaigns",
        ["tenant_id", "owner_id"],
        unique=False,
    )

    op.create_table(
        "crm_campaign_members",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("campaign_id", UUID, nullable=False),
        sa.Column("member_type", sa.String(length=20), nullable=False),
        sa.Column("member_id", UUID, nullable=False),
        sa.Column(
            "member_status",
            sa.String(length=20),
            server_default=sa.text("'PLANNED'"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["campaign_id"], ["crm_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "campaign_id",
            "member_type",
            "member_id",
            name="uq_crm_campaign_members_tenant_campaign_member",
        ),
    )
    op.create_index(
        "ix_crm_campaign_members_campaign_id",
        "crm_campaign_members",
        ["campaign_id"],
        unique=False,
    )
    op.create_index(
        "ix_crm_campaign_members_tenant_member",
        "crm_campaign_members",
        ["tenant_id", "member_type", "member_id"],
        unique=False,
    )

    op.add_column("crm_leads", sa.Column("campaign_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_crm_leads_campaign_id",
        "crm_leads",
        "crm_campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_crm_leads_tenant_id_campaign_id",
        "crm_leads",
        ["tenant_id", "campaign_id"],
        unique=False,
    )

    op.add_column("crm_opportunities", sa.Column("campaign_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_crm_opportunities_campaign_id",
        "crm_opportunities",
        "crm_campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_crm_opportunities_tenant_id_campaign_id",
        "crm_opportunities",
        ["tenant_id", "campaign_id"],
        unique=False,
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
    op.drop_index("ix_crm_opportunities_tenant_id_campaign_id", table_name="crm_opportunities")
    op.drop_constraint("fk_crm_opportunities_campaign_id", "crm_opportunities", type_="foreignkey")
    op.drop_column("crm_opportunities", "campaign_id")

    op.drop_index("ix_crm_leads_tenant_id_campaign_id", table_name="crm_leads")
    op.drop_constraint("fk_crm_leads_campaign_id", "crm_leads", type_="foreignkey")
    op.drop_column("crm_leads", "campaign_id")

    op.drop_index("ix_crm_campaign_members_tenant_member", table_name="crm_campaign_members")
    op.drop_index("ix_crm_campaign_members_campaign_id", table_name="crm_campaign_members")
    op.drop_table("crm_campaign_members")

    op.drop_index("ix_crm_campaigns_tenant_id_owner_id", table_name="crm_campaigns")
    op.drop_index("ix_crm_campaigns_tenant_id_status", table_name="crm_campaigns")
    op.drop_index("uq_crm_campaigns_tenant_id_name_active", table_name="crm_campaigns")
    op.drop_index("ix_crm_campaigns_tenant_id", table_name="crm_campaigns")
    op.drop_table("crm_campaigns")
