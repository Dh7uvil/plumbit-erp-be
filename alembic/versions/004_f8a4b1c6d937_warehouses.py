"""warehouses

Revision ID: f8a4b1c6d937
Revises: e7b2c9d4a813
Create Date: 2026-08-27 09:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "f8a4b1c6d937"
down_revision: str | Sequence[str] | None = "e7b2c9d4a813"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def _pk() -> sa.Column:
    return sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False)


def _tenant() -> sa.Column:
    return sa.Column("tenant_id", UUID, nullable=False)


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def _soft_delete() -> sa.Column:
    return sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)


def _audit_users() -> list[sa.Column]:
    return [
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
    ]


def _is_active() -> sa.Column:
    return sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False)


def upgrade() -> None:
    """Apply this revision."""
    op.create_table(
        "warehouses",
        _pk(),
        _tenant(),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("address_id", UUID, nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        _is_active(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["address_id"], ["addresses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_warehouses_tenant_id", "warehouses", ["tenant_id"])
    op.create_index("ix_warehouses_address_id", "warehouses", ["address_id"])
    op.create_index(
        "uq_warehouses_tenant_id_code_active",
        "warehouses",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_warehouses_tenant_id_default_active",
        "warehouses",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default IS TRUE AND deleted_at IS NULL"),
    )

    _backfill_catalog_and_main_warehouse()


def _backfill_catalog_and_main_warehouse() -> None:
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

        already = bind.execute(
            sa.text(
                """
                SELECT id FROM warehouses
                WHERE tenant_id = :tenant_id AND deleted_at IS NULL
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if already is not None:
            continue

        bind.execute(
            sa.text(
                """
                INSERT INTO warehouses (tenant_id, code, name, is_default)
                VALUES (:tenant_id, 'MAIN', 'Main Warehouse', true)
                """
            ),
            {"tenant_id": tenant_id},
        )


def downgrade() -> None:
    """Revert this revision."""
    op.drop_table("warehouses")
