"""Product purchase information and Superadmin grants for order permissions.

Revision ID: a8c3e7f2b461
Revises: e4c8b2f7a319
Create Date: 2026-09-08 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8c3e7f2b461"
down_revision: str | Sequence[str] | None = "e4c8b2f7a319"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORDER_PERMISSIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sales_order", ("create", "read", "update", "delete", "approve", "confirm", "close")),
    ("purchase_order", ("create", "read", "update", "delete", "approve", "issue", "close")),
)


def upgrade() -> None:
    """Add product purchase fields and grant erp.sales_order.* / erp.purchase_order.*."""

    op.add_column(
        "products",
        sa.Column(
            "purchase_rate",
            sa.Numeric(18, 4),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column("products", sa.Column("purchase_description", sa.Text(), nullable=True))
    _backfill_order_permissions()


def downgrade() -> None:
    """Drop product purchase fields and remove order permission catalog rows."""

    op.execute(
        sa.text(
            """
            DELETE FROM permissions
            WHERE module = 'erp'
              AND resource IN ('sales_order', 'purchase_order')
            """
        )
    )
    op.drop_column("products", "purchase_description")
    op.drop_column("products", "purchase_rate")


def _backfill_order_permissions() -> None:
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
        for resource, actions in _ORDER_PERMISSIONS:
            for action in actions:
                key = ("erp", resource, action)
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
                        "module": "erp",
                        "resource": resource,
                        "action": action,
                    },
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
                  AND p.resource IN ('sales_order', 'purchase_order')
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
