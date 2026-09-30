"""Winsoft parity: year-end, VAT-inclusive pricing, PO charges/metrics.

Revision ID: f2a3b4c5d608
Revises: e1f2a3b4c507
Create Date: 2026-09-29 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "f2a3b4c5d608"
down_revision: str | None = "e1f2a3b4c507"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
_MONEY = sa.Numeric(18, 4)
_QTY = sa.Numeric(18, 6)

_COMMERCIAL_HEADERS = (
    "quotations",
    "sales_orders",
    "sales_invoices",
    "proforma_invoices",
    "purchase_orders",
    "purchase_invoices",
    "credit_notes",
    "debit_notes",
)


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "prices_include_tax_default",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    for table in _COMMERCIAL_HEADERS:
        op.add_column(
            table,
            sa.Column(
                "prices_include_tax",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
        )

    op.add_column(
        "purchase_order_lines",
        sa.Column(
            "line_type",
            sa.String(length=30),
            server_default=sa.text("'PRODUCT'"),
            nullable=False,
        ),
    )
    op.add_column("purchase_order_lines", sa.Column("expense_account_id", UUID, nullable=True))
    op.add_column(
        "purchase_order_lines",
        sa.Column("expense_category", sa.String(length=30), nullable=True),
    )
    op.add_column("purchase_order_lines", sa.Column("charge_type_id", UUID, nullable=True))
    op.add_column("purchase_order_lines", sa.Column("net_weight", _QTY, nullable=True))
    op.add_column("purchase_order_lines", sa.Column("gross_weight", _QTY, nullable=True))
    op.add_column("purchase_order_lines", sa.Column("volume", _QTY, nullable=True))
    op.create_foreign_key(
        "fk_purchase_order_lines_expense_account_id",
        "purchase_order_lines",
        "accounts",
        ["expense_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_purchase_order_lines_charge_type_id",
        "purchase_order_lines",
        "charge_types",
        ["charge_type_id"],
        ["id"],
        ondelete="SET NULL",
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
                WHERE tenant_id = :tenant_id AND is_system_role = true
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
                        SELECT 1 FROM role_permissions rp
                        WHERE rp.tenant_id = :tenant_id
                          AND rp.role_id = :role_id
                          AND rp.permission_id = p.id
                      )
                    """
                ),
                {"tenant_id": tenant_id, "role_id": admin.id},
            )


def downgrade() -> None:
    op.drop_constraint(
        "fk_purchase_order_lines_charge_type_id",
        "purchase_order_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_purchase_order_lines_expense_account_id", "purchase_order_lines", type_="foreignkey"
    )
    op.drop_column("purchase_order_lines", "volume")
    op.drop_column("purchase_order_lines", "gross_weight")
    op.drop_column("purchase_order_lines", "net_weight")
    op.drop_column("purchase_order_lines", "charge_type_id")
    op.drop_column("purchase_order_lines", "expense_category")
    op.drop_column("purchase_order_lines", "expense_account_id")
    op.drop_column("purchase_order_lines", "line_type")
    for table in reversed(_COMMERCIAL_HEADERS):
        op.drop_column(table, "prices_include_tax")
    op.drop_column("tenants", "prices_include_tax_default")
