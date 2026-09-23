"""Accounting robustness: base amounts, schedule_day, unique active budget.

Revision ID: c0d1e2f3a189
Revises: b8c9d0e1f188
Create Date: 2026-09-23 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0d1e2f3a189"
down_revision: str | None = "b8c9d0e1f188"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(18, 4)


def upgrade() -> None:
    op.add_column(
        "landed_cost_charges",
        sa.Column("base_amount", MONEY, server_default=sa.text("0"), nullable=False),
    )
    op.execute(
        """
        UPDATE landed_cost_charges lc
        SET base_amount = lc.amount * COALESCE(pi.exchange_rate, 1)
        FROM purchase_invoices pi
        WHERE lc.purchase_invoice_id = pi.id
        """
    )

    op.add_column(
        "recurring_templates",
        sa.Column("schedule_day", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.execute(
        """
        UPDATE recurring_templates
        SET schedule_day = EXTRACT(DAY FROM next_run_date)::int
        """
    )

    op.add_column(
        "payment_allocations",
        sa.Column("base_amount", MONEY, nullable=True),
    )

    op.add_column(
        "invoice_write_offs",
        sa.Column("base_amount", MONEY, server_default=sa.text("0"), nullable=False),
    )
    op.execute(
        """
        UPDATE invoice_write_offs wo
        SET base_amount = wo.amount * COALESCE(si.exchange_rate, 1)
        FROM sales_invoices si
        WHERE wo.document_kind = 'SALES_INVOICE'
          AND wo.invoice_id = si.id
        """
    )
    op.execute(
        """
        UPDATE invoice_write_offs wo
        SET base_amount = wo.amount * COALESCE(pi.exchange_rate, 1)
        FROM purchase_invoices pi
        WHERE wo.document_kind = 'PURCHASE_INVOICE'
          AND wo.invoice_id = pi.id
        """
    )

    op.execute(
        """
        UPDATE payment_allocations pa
        SET base_amount = pa.amount * COALESCE(
            (SELECT exchange_rate FROM sales_invoices si
             WHERE pa.item_type = 'SALES_INVOICE' AND pa.item_id = si.id),
            (SELECT exchange_rate FROM purchase_invoices pi
             WHERE pa.item_type = 'PURCHASE_INVOICE' AND pa.item_id = pi.id),
            (SELECT jel.exchange_rate FROM journal_entry_lines jel
             WHERE pa.item_type IN ('OPENING_AR', 'OPENING_AP') AND pa.item_id = jel.id),
            1
        )
        WHERE pa.base_amount IS NULL
        """
    )

    op.add_column("cost_sheets", sa.Column("base_total", MONEY, nullable=True))
    op.add_column("cost_sheet_lines", sa.Column("base_amount", MONEY, nullable=True))

    op.add_column("bank_statements", sa.Column("base_opening_balance", MONEY, nullable=True))
    op.add_column("bank_statements", sa.Column("base_closing_balance", MONEY, nullable=True))

    op.create_index(
        "uq_budgets_tenant_fiscal_year_active",
        "budgets",
        ["tenant_id", "fiscal_year"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND status = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_index("uq_budgets_tenant_fiscal_year_active", table_name="budgets")
    op.drop_column("bank_statements", "base_closing_balance")
    op.drop_column("bank_statements", "base_opening_balance")
    op.drop_column("cost_sheet_lines", "base_amount")
    op.drop_column("cost_sheets", "base_total")
    op.drop_column("invoice_write_offs", "base_amount")
    op.drop_column("payment_allocations", "base_amount")
    op.drop_column("recurring_templates", "schedule_day")
    op.drop_column("landed_cost_charges", "base_amount")
