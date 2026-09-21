"""CRM activities and notes.

Revision ID: e5f8a1b4c017
Revises: d4e7f0a3b016
Create Date: 2026-09-21 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "e5f8a1b4c017"
down_revision: str | None = "d4e7f0a3b016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "crm_activities",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("activity_type", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column(
            "priority",
            sa.String(length=20),
            server_default=sa.text("'MEDIUM'"),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("owner_id", UUID, nullable=True),
        sa.Column("related_entity_type", sa.String(length=30), nullable=False),
        sa.Column("related_entity_id", UUID, nullable=False),
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
    op.create_index("ix_crm_activities_tenant_id", "crm_activities", ["tenant_id"], unique=False)
    op.create_index(
        "ix_crm_activities_tenant_related",
        "crm_activities",
        ["tenant_id", "related_entity_type", "related_entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_crm_activities_tenant_owner_due",
        "crm_activities",
        ["tenant_id", "owner_id", "due_at"],
        unique=False,
    )
    op.create_index(
        "ix_crm_activities_tenant_id_status",
        "crm_activities",
        ["tenant_id", "status"],
        unique=False,
    )

    op.create_table(
        "crm_notes",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("related_entity_type", sa.String(length=30), nullable=False),
        sa.Column("related_entity_id", UUID, nullable=False),
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
    op.create_index("ix_crm_notes_tenant_id", "crm_notes", ["tenant_id"], unique=False)
    op.create_index(
        "ix_crm_notes_tenant_related",
        "crm_notes",
        ["tenant_id", "related_entity_type", "related_entity_id"],
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
    op.drop_index("ix_crm_notes_tenant_related", table_name="crm_notes")
    op.drop_index("ix_crm_notes_tenant_id", table_name="crm_notes")
    op.drop_table("crm_notes")

    op.drop_index("ix_crm_activities_tenant_id_status", table_name="crm_activities")
    op.drop_index("ix_crm_activities_tenant_owner_due", table_name="crm_activities")
    op.drop_index("ix_crm_activities_tenant_related", table_name="crm_activities")
    op.drop_index("ix_crm_activities_tenant_id", table_name="crm_activities")
    op.drop_table("crm_activities")
