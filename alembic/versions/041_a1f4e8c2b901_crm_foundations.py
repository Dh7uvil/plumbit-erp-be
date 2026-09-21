"""CRM foundations: pipelines, lead sources, lost reasons.

Revision ID: a1f4e8c2b901
Revises: c9d3e5f1a234
Create Date: 2026-09-21 18:00:00.000000
"""

from collections.abc import Sequence
from decimal import Decimal
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions
from app.crm.foundations.defaults import (
    DEFAULT_LEAD_SOURCES,
    DEFAULT_PIPELINE_NAME,
    DEFAULT_PIPELINE_STAGES,
)

revision: str = "a1f4e8c2b901"
down_revision: str | None = "c9d3e5f1a234"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "crm_pipelines",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crm_pipelines_tenant_id", "crm_pipelines", ["tenant_id"], unique=False)
    op.create_index(
        "uq_crm_pipelines_tenant_id_name_active",
        "crm_pipelines",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_crm_pipelines_tenant_id_default_active",
        "crm_pipelines",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default IS TRUE AND deleted_at IS NULL"),
    )

    op.create_table(
        "crm_pipeline_stages",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("pipeline_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("probability", sa.Numeric(19, 4), nullable=False),
        sa.Column("stage_kind", sa.String(length=20), nullable=False),
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
        sa.ForeignKeyConstraint(["pipeline_id"], ["crm_pipelines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_crm_pipeline_stages_pipeline_id",
        "crm_pipeline_stages",
        ["pipeline_id"],
        unique=False,
    )
    op.create_index(
        "uq_crm_pipeline_stages_tenant_pipeline_name",
        "crm_pipeline_stages",
        ["tenant_id", "pipeline_id", "name"],
        unique=True,
    )

    op.create_table(
        "crm_lead_sources",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_crm_lead_sources_tenant_id", "crm_lead_sources", ["tenant_id"], unique=False
    )
    op.create_index(
        "uq_crm_lead_sources_tenant_id_name_active",
        "crm_lead_sources",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "crm_lost_reasons",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_crm_lost_reasons_tenant_id", "crm_lost_reasons", ["tenant_id"], unique=False
    )
    op.create_index(
        "uq_crm_lost_reasons_tenant_id_name_active",
        "crm_lost_reasons",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    _seed_crm_foundations()
    _backfill_catalog_permissions()


def _seed_crm_foundations() -> None:
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    for (tenant_id,) in tenants:
        existing_pipeline = bind.execute(
            sa.text(
                """
                SELECT id FROM crm_pipelines
                WHERE tenant_id = :tenant_id AND deleted_at IS NULL
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if existing_pipeline is None:
            pipeline_id = uuid4()
            bind.execute(
                sa.text(
                    """
                    INSERT INTO crm_pipelines (
                        id, tenant_id, name, is_default, is_active
                    ) VALUES (
                        :id, :tenant_id, :name, true, true
                    )
                    """
                ),
                {
                    "id": pipeline_id,
                    "tenant_id": tenant_id,
                    "name": DEFAULT_PIPELINE_NAME,
                },
            )
            for name, sort_order, probability, stage_kind in DEFAULT_PIPELINE_STAGES:
                bind.execute(
                    sa.text(
                        """
                        INSERT INTO crm_pipeline_stages (
                            id, tenant_id, pipeline_id, name, sort_order, probability, stage_kind
                        ) VALUES (
                            :id, :tenant_id, :pipeline_id, :name, :sort_order,
                            :probability, :stage_kind
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "pipeline_id": pipeline_id,
                        "name": name,
                        "sort_order": sort_order,
                        "probability": Decimal(probability),
                        "stage_kind": stage_kind.value,
                    },
                )

        existing_sources = {
            row[0]
            for row in bind.execute(
                sa.text(
                    """
                    SELECT name FROM crm_lead_sources
                    WHERE tenant_id = :tenant_id AND deleted_at IS NULL
                    """
                ),
                {"tenant_id": tenant_id},
            ).fetchall()
        }
        for source_name in DEFAULT_LEAD_SOURCES:
            if source_name in existing_sources:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO crm_lead_sources (id, tenant_id, name, is_active)
                    VALUES (:id, :tenant_id, :name, true)
                    """
                ),
                {"id": uuid4(), "tenant_id": tenant_id, "name": source_name},
            )


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
    op.drop_index("uq_crm_lost_reasons_tenant_id_name_active", table_name="crm_lost_reasons")
    op.drop_index("ix_crm_lost_reasons_tenant_id", table_name="crm_lost_reasons")
    op.drop_table("crm_lost_reasons")

    op.drop_index("uq_crm_lead_sources_tenant_id_name_active", table_name="crm_lead_sources")
    op.drop_index("ix_crm_lead_sources_tenant_id", table_name="crm_lead_sources")
    op.drop_table("crm_lead_sources")

    op.drop_index(
        "uq_crm_pipeline_stages_tenant_pipeline_name", table_name="crm_pipeline_stages"
    )
    op.drop_index("ix_crm_pipeline_stages_pipeline_id", table_name="crm_pipeline_stages")
    op.drop_table("crm_pipeline_stages")

    op.drop_index("uq_crm_pipelines_tenant_id_default_active", table_name="crm_pipelines")
    op.drop_index("uq_crm_pipelines_tenant_id_name_active", table_name="crm_pipelines")
    op.drop_index("ix_crm_pipelines_tenant_id", table_name="crm_pipelines")
    op.drop_table("crm_pipelines")
