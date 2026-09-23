"""Cross-conversion gaps: note refunds and invoice-sourced fulfillment links.

Revision ID: e2f3a4b5c191
Revises: d1e2f3a4b190
Create Date: 2026-09-23 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e2f3a4b5c191"
down_revision: str | Sequence[str] | None = "d1e2f3a4b190"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
QTY = sa.Numeric(18, 6)
MONEY = sa.Numeric(18, 4)


def upgrade() -> None:
    for table in ("credit_notes", "debit_notes"):
        op.add_column(
            table,
            sa.Column("amount_refunded", MONEY, server_default=sa.text("0"), nullable=False),
        )
        op.add_column(table, sa.Column("refund_journal_entry_id", UUID, nullable=True))
        op.add_column(table, sa.Column("refund_payment_account_id", UUID, nullable=True))
        op.add_column(table, sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("refunded_by", UUID, nullable=True))
        op.create_foreign_key(
            f"fk_{table}_refund_journal_entry_id",
            table,
            "journal_entries",
            ["refund_journal_entry_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_foreign_key(
            f"fk_{table}_refund_payment_account_id",
            table,
            "accounts",
            ["refund_payment_account_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_foreign_key(
            f"fk_{table}_refunded_by",
            table,
            "users",
            ["refunded_by"],
            ["id"],
            ondelete="SET NULL",
        )

    op.add_column(
        "sales_invoice_lines",
        sa.Column("qty_delivered", QTY, server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "purchase_invoice_lines",
        sa.Column("qty_received", QTY, server_default=sa.text("0"), nullable=False),
    )

    op.add_column("delivery_notes", sa.Column("source_sales_invoice_id", UUID, nullable=True))
    op.alter_column("delivery_notes", "sales_order_id", existing_type=UUID, nullable=True)
    op.create_foreign_key(
        "fk_delivery_notes_source_sales_invoice_id",
        "delivery_notes",
        "sales_invoices",
        ["source_sales_invoice_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_delivery_notes_tenant_id_source_sales_invoice_id",
        "delivery_notes",
        ["tenant_id", "source_sales_invoice_id"],
    )

    op.add_column(
        "delivery_note_lines",
        sa.Column("source_sales_invoice_line_id", UUID, nullable=True),
    )
    op.alter_column("delivery_note_lines", "sales_order_line_id", existing_type=UUID, nullable=True)
    op.create_foreign_key(
        "fk_delivery_note_lines_source_sales_invoice_line_id",
        "delivery_note_lines",
        "sales_invoice_lines",
        ["source_sales_invoice_line_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_delivery_note_lines_source_sales_invoice_line_id",
        "delivery_note_lines",
        ["source_sales_invoice_line_id"],
    )

    op.add_column("goods_receipts", sa.Column("source_purchase_invoice_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_goods_receipts_source_purchase_invoice_id",
        "goods_receipts",
        "purchase_invoices",
        ["source_purchase_invoice_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_goods_receipts_tenant_id_source_purchase_invoice_id",
        "goods_receipts",
        ["tenant_id", "source_purchase_invoice_id"],
    )
    op.add_column(
        "goods_receipt_lines",
        sa.Column("source_purchase_invoice_line_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_goods_receipt_lines_source_purchase_invoice_line_id",
        "goods_receipt_lines",
        "purchase_invoice_lines",
        ["source_purchase_invoice_line_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_goods_receipt_lines_source_purchase_invoice_line_id",
        "goods_receipt_lines",
        ["source_purchase_invoice_line_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_goods_receipts_tenant_id_source_purchase_invoice_id",
        table_name="goods_receipts",
    )
    op.drop_constraint(
        "fk_goods_receipts_source_purchase_invoice_id",
        "goods_receipts",
        type_="foreignkey",
    )
    op.drop_column("goods_receipts", "source_purchase_invoice_id")
    op.drop_index(
        "ix_goods_receipt_lines_source_purchase_invoice_line_id",
        table_name="goods_receipt_lines",
    )
    op.drop_constraint(
        "fk_goods_receipt_lines_source_purchase_invoice_line_id",
        "goods_receipt_lines",
        type_="foreignkey",
    )
    op.drop_column("goods_receipt_lines", "source_purchase_invoice_line_id")

    op.drop_index(
        "ix_delivery_note_lines_source_sales_invoice_line_id",
        table_name="delivery_note_lines",
    )
    op.drop_constraint(
        "fk_delivery_note_lines_source_sales_invoice_line_id",
        "delivery_note_lines",
        type_="foreignkey",
    )
    op.alter_column("delivery_note_lines", "sales_order_line_id", existing_type=UUID, nullable=False)
    op.drop_column("delivery_note_lines", "source_sales_invoice_line_id")

    op.drop_index(
        "ix_delivery_notes_tenant_id_source_sales_invoice_id",
        table_name="delivery_notes",
    )
    op.drop_constraint(
        "fk_delivery_notes_source_sales_invoice_id",
        "delivery_notes",
        type_="foreignkey",
    )
    op.alter_column("delivery_notes", "sales_order_id", existing_type=UUID, nullable=False)
    op.drop_column("delivery_notes", "source_sales_invoice_id")

    op.drop_column("purchase_invoice_lines", "qty_received")
    op.drop_column("sales_invoice_lines", "qty_delivered")

    for table in ("credit_notes", "debit_notes"):
        op.drop_constraint(f"fk_{table}_refunded_by", table, type_="foreignkey")
        op.drop_constraint(f"fk_{table}_refund_payment_account_id", table, type_="foreignkey")
        op.drop_constraint(f"fk_{table}_refund_journal_entry_id", table, type_="foreignkey")
        op.drop_column(table, "refunded_by")
        op.drop_column(table, "refunded_at")
        op.drop_column(table, "refund_payment_account_id")
        op.drop_column(table, "refund_journal_entry_id")
        op.drop_column(table, "amount_refunded")
