"""Item account mapping and new chart roles.

Revision ID: d2e5f9b7c013
Revises: c1d4e8a6b902
Create Date: 2026-09-10 19:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d2e5f9b7c013"
down_revision: str | Sequence[str] | None = "c1d4e8a6b902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    """Apply this revision."""
    op.add_column("products", sa.Column("income_account_id", UUID, nullable=True))
    op.add_column("products", sa.Column("purchase_account_id", UUID, nullable=True))
    op.create_index("ix_products_income_account_id", "products", ["income_account_id"])
    op.create_index("ix_products_purchase_account_id", "products", ["purchase_account_id"])
    op.create_foreign_key(
        "fk_products_income_account_id",
        "products",
        "accounts",
        ["income_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_products_purchase_account_id",
        "products",
        "accounts",
        ["purchase_account_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("categories", sa.Column("income_account_id", UUID, nullable=True))
    op.add_column("categories", sa.Column("purchase_account_id", UUID, nullable=True))
    op.create_index("ix_categories_income_account_id", "categories", ["income_account_id"])
    op.create_index("ix_categories_purchase_account_id", "categories", ["purchase_account_id"])
    op.create_foreign_key(
        "fk_categories_income_account_id",
        "categories",
        "accounts",
        ["income_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_categories_purchase_account_id",
        "categories",
        "accounts",
        ["purchase_account_id"],
        ["id"],
        ondelete="SET NULL",
    )

    _backfill_chart_roles()


def _backfill_chart_roles() -> None:
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    for (tenant_id,) in tenants:
        parent_liability = bind.execute(
            sa.text(
                """
                SELECT id, depth FROM accounts
                WHERE tenant_id = :tenant_id AND code = '2000' AND deleted_at IS NULL
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        parent_income = bind.execute(
            sa.text(
                """
                SELECT id, depth FROM accounts
                WHERE tenant_id = :tenant_id AND code = '4000' AND deleted_at IS NULL
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if parent_liability is not None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO accounts (
                        tenant_id, code, name, account_type, account_subtype, parent_id,
                        depth, is_group, is_system, system_role, is_active
                    )
                    SELECT :tenant_id, '2030', 'Goods Received Not Invoiced', 'LIABILITY',
                           'OTHER_CURRENT_LIABILITY', :parent_id, :depth, false, true,
                           'GOODS_RECEIVED_NOT_INVOICED', true
                    WHERE NOT EXISTS (
                        SELECT 1 FROM accounts
                        WHERE tenant_id = :tenant_id AND code = '2030' AND deleted_at IS NULL
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM accounts
                        WHERE tenant_id = :tenant_id
                          AND system_role = 'GOODS_RECEIVED_NOT_INVOICED'
                          AND deleted_at IS NULL
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "parent_id": parent_liability.id,
                    "depth": parent_liability.depth + 1,
                },
            )
        if parent_income is not None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO accounts (
                        tenant_id, code, name, account_type, account_subtype, parent_id,
                        depth, is_group, is_system, system_role, is_active
                    )
                    SELECT :tenant_id, '4110', 'Shipping Income', 'INCOME', 'INCOME',
                           :parent_id, :depth, false, true, 'SHIPPING_INCOME', true
                    WHERE NOT EXISTS (
                        SELECT 1 FROM accounts
                        WHERE tenant_id = :tenant_id AND code = '4110' AND deleted_at IS NULL
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM accounts
                        WHERE tenant_id = :tenant_id
                          AND system_role = 'SHIPPING_INCOME'
                          AND deleted_at IS NULL
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "parent_id": parent_income.id,
                    "depth": parent_income.depth + 1,
                },
            )
            bind.execute(
                sa.text(
                    """
                    UPDATE accounts
                    SET system_role = 'OTHER_CHARGES', is_system = true
                    WHERE tenant_id = :tenant_id
                      AND code = '4300'
                      AND deleted_at IS NULL
                      AND system_role IS NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM accounts a2
                        WHERE a2.tenant_id = :tenant_id
                          AND a2.system_role = 'OTHER_CHARGES'
                          AND a2.deleted_at IS NULL
                      )
                    """
                ),
                {"tenant_id": tenant_id},
            )


def downgrade() -> None:
    """Revert this revision."""
    op.execute(
        sa.text(
            """
            UPDATE accounts SET system_role = NULL
            WHERE system_role IN (
                'GOODS_RECEIVED_NOT_INVOICED', 'SHIPPING_INCOME', 'OTHER_CHARGES'
            )
            """
        )
    )
    op.execute(sa.text("DELETE FROM accounts WHERE code IN ('2030', '4110') AND is_system = true"))
    op.drop_constraint("fk_categories_purchase_account_id", "categories", type_="foreignkey")
    op.drop_constraint("fk_categories_income_account_id", "categories", type_="foreignkey")
    op.drop_index("ix_categories_purchase_account_id", table_name="categories")
    op.drop_index("ix_categories_income_account_id", table_name="categories")
    op.drop_column("categories", "purchase_account_id")
    op.drop_column("categories", "income_account_id")
    op.drop_constraint("fk_products_purchase_account_id", "products", type_="foreignkey")
    op.drop_constraint("fk_products_income_account_id", "products", type_="foreignkey")
    op.drop_index("ix_products_purchase_account_id", table_name="products")
    op.drop_index("ix_products_income_account_id", table_name="products")
    op.drop_column("products", "purchase_account_id")
    op.drop_column("products", "income_account_id")
