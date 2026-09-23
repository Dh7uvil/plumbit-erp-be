"""Backfill Bad Debt Expense system account for existing tenants.

Revision ID: d1e2f3a4b190
Revises: c0d1e2f3a189
Create Date: 2026-09-23 12:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e2f3a4b190"
down_revision: str | None = "c0d1e2f3a189"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    for (tenant_id,) in tenants:
        parent_expense = bind.execute(
            sa.text(
                """
                SELECT id, depth FROM accounts
                WHERE tenant_id = :tenant_id AND code = '6000' AND deleted_at IS NULL
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if parent_expense is None:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO accounts (
                    tenant_id, code, name, account_type, account_subtype, parent_id,
                    depth, is_group, is_system, system_role, is_active
                )
                SELECT :tenant_id, '6150', 'Bad Debt Expense', 'EXPENSE',
                       'OTHER_EXPENSE', :parent_id, :depth, false, true,
                       'BAD_DEBT_EXPENSE', true
                WHERE NOT EXISTS (
                    SELECT 1 FROM accounts
                    WHERE tenant_id = :tenant_id
                      AND system_role = 'BAD_DEBT_EXPENSE'
                      AND deleted_at IS NULL
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "parent_id": parent_expense.id,
                "depth": parent_expense.depth + 1,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE accounts
            SET deleted_at = now(), system_role = NULL
            WHERE code = '6150'
              AND system_role = 'BAD_DEBT_EXPENSE'
              AND deleted_at IS NULL
              AND is_system = true
            """
        )
    )
