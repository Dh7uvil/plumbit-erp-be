"""Supplier product catalog and permission backfill.

Revision ID: a5d8c2e7b410
Revises: f4c9e6a1d235
Create Date: 2026-09-09 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a5d8c2e7b410"
down_revision: str | Sequence[str] | None = "f4c9e6a1d235"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)

_ACTIONS = ("create", "read", "update", "delete", "link")


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


def upgrade() -> None:
    """Create supplier_products and grant erp.supplier_product.* to Superadmin."""

    op.create_table(
        "supplier_products",
        _pk(),
        _tenant(),
        sa.Column("supplier_id", UUID, nullable=False),
        sa.Column("product_id", UUID, nullable=True),
        sa.Column("supplier_sku", sa.String(length=80), nullable=False),
        sa.Column("supplier_sku_normalized", sa.String(length=80), nullable=False),
        sa.Column("supplier_item_name", sa.String(length=200), nullable=False),
        sa.Column("supplier_description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("price_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_preferred",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_preferred_supplier",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_supplier_products_tenant_id", "supplier_products", ["tenant_id"])
    op.create_index("ix_supplier_products_supplier_id", "supplier_products", ["supplier_id"])
    op.create_index("ix_supplier_products_product_id", "supplier_products", ["product_id"])
    op.create_index("ix_supplier_products_currency_id", "supplier_products", ["currency_id"])
    op.create_index(
        "ix_supplier_products_tenant_id_product_id",
        "supplier_products",
        ["tenant_id", "product_id"],
    )
    op.create_index(
        "uq_supplier_products_tenant_supplier_sku_active",
        "supplier_products",
        ["tenant_id", "supplier_id", "supplier_sku_normalized"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_supplier_products_tenant_supplier_product_preferred",
        "supplier_products",
        ["tenant_id", "supplier_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND is_preferred IS TRUE"),
    )
    op.create_index(
        "uq_supplier_products_tenant_product_preferred_supplier",
        "supplier_products",
        ["tenant_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND is_preferred_supplier IS TRUE"),
    )
    _backfill_permissions()


def downgrade() -> None:
    """Drop supplier_products and the supplier_product catalog rows."""

    op.execute(
        sa.text(
            """
            DELETE FROM permissions
            WHERE module = 'erp'
              AND resource = 'supplier_product'
              AND action IN ('create', 'read', 'update', 'delete', 'link')
            """
        )
    )
    op.drop_index(
        "uq_supplier_products_tenant_product_preferred_supplier",
        table_name="supplier_products",
    )
    op.drop_index(
        "uq_supplier_products_tenant_supplier_product_preferred",
        table_name="supplier_products",
    )
    op.drop_index(
        "uq_supplier_products_tenant_supplier_sku_active",
        table_name="supplier_products",
    )
    op.drop_index("ix_supplier_products_tenant_id_product_id", table_name="supplier_products")
    op.drop_index("ix_supplier_products_currency_id", table_name="supplier_products")
    op.drop_index("ix_supplier_products_product_id", table_name="supplier_products")
    op.drop_index("ix_supplier_products_supplier_id", table_name="supplier_products")
    op.drop_index("ix_supplier_products_tenant_id", table_name="supplier_products")
    op.drop_table("supplier_products")


def _backfill_permissions() -> None:
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    for (tenant_id,) in tenants:
        existing = bind.execute(
            sa.text(
                "SELECT module, resource, action FROM permissions WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).fetchall()
        existing_keys = {(row.module, row.resource, row.action) for row in existing}
        for action in _ACTIONS:
            key = ("erp", "supplier_product", action)
            if key in existing_keys:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO permissions (tenant_id, module, resource, action)
                    VALUES (:tenant_id, 'erp', 'supplier_product', :action)
                    """
                ),
                {"tenant_id": tenant_id, "action": action},
            )

        admin = bind.execute(
            sa.text(
                """
                SELECT id FROM roles
                WHERE tenant_id = :tenant_id
                  AND name = 'Superadmin'
                  AND is_system_role IS TRUE
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if admin is None:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO role_permissions (tenant_id, role_id, permission_id)
                SELECT :tenant_id, :role_id, p.id
                FROM permissions p
                WHERE p.tenant_id = :tenant_id
                  AND p.module = 'erp'
                  AND p.resource = 'supplier_product'
                  AND p.action IN ('create', 'read', 'update', 'delete', 'link')
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
