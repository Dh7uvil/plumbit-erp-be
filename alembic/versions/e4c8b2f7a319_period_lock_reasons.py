"""Period lock reason columns and Superadmin grants for erp.period.*.

Revision ID: e4c8b2f7a319
Revises: d1e5f8a2c904
Create Date: 2026-09-08 16:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4c8b2f7a319"
down_revision: str | Sequence[str] | None = "d1e5f8a2c904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERIOD_PERMISSIONS = ("lock", "override")


def upgrade() -> None:
    """Add lock reason columns and grant erp.period.lock / override to Superadmin."""

    op.add_column("tenants", sa.Column("lock_reason", sa.String(length=500), nullable=True))
    op.add_column("tenants", sa.Column("hard_lock_reason", sa.String(length=500), nullable=True))
    _backfill_period_permissions()


def downgrade() -> None:
    """Drop lock reason columns and remove erp.period.* catalog rows."""

    op.execute(
        sa.text(
            """
            DELETE FROM permissions
            WHERE module = 'erp'
              AND resource = 'period'
              AND action IN ('lock', 'override')
            """
        )
    )
    op.drop_column("tenants", "hard_lock_reason")
    op.drop_column("tenants", "lock_reason")


def _backfill_period_permissions() -> None:
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
        for action in _PERIOD_PERMISSIONS:
            key = ("erp", "period", action)
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
                    "resource": "period",
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
                  AND p.resource = 'period'
                  AND p.action IN ('lock', 'override')
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
