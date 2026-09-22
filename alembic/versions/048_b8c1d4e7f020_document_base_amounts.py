"""Add base_amount and foreign_amount to GRN, DN, and payments.

Revision ID: b8c1d4e7f020
Revises: a7b0c3d6e019
Create Date: 2026-09-22 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8c1d4e7f020"
down_revision: str | None = "a7b0c3d6e019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(18, 4)


def _add_money_columns(table: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns(table)}
    if "foreign_amount" not in existing:
        op.add_column(
            table,
            sa.Column("foreign_amount", MONEY, server_default=sa.text("0"), nullable=False),
        )
    if "base_amount" not in existing:
        op.add_column(
            table,
            sa.Column("base_amount", MONEY, server_default=sa.text("0"), nullable=False),
        )


def upgrade() -> None:
    for table in (
        "goods_receipts",
        "delivery_notes",
        "customer_payments",
        "supplier_payments",
    ):
        _add_money_columns(table)

    op.execute(
        sa.text(
            """
            UPDATE goods_receipts AS header
            SET
                foreign_amount = totals.foreign_amount,
                base_amount = ROUND(totals.foreign_amount * header.exchange_rate, 4)
            FROM (
                SELECT
                    goods_receipt_id,
                    COALESCE(SUM(quantity * rate), 0) AS foreign_amount
                FROM goods_receipt_lines
                GROUP BY goods_receipt_id
            ) AS totals
            WHERE totals.goods_receipt_id = header.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE delivery_notes AS header
            SET
                foreign_amount = totals.foreign_amount,
                base_amount = ROUND(totals.foreign_amount * header.exchange_rate, 4)
            FROM (
                SELECT
                    delivery_note_id,
                    COALESCE(SUM(quantity * rate), 0) AS foreign_amount
                FROM delivery_note_lines
                GROUP BY delivery_note_id
            ) AS totals
            WHERE totals.delivery_note_id = header.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE customer_payments
            SET
                foreign_amount = amount_received,
                base_amount = ROUND(amount_received * exchange_rate, 4)
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE supplier_payments
            SET
                foreign_amount = amount_paid,
                base_amount = ROUND(amount_paid * exchange_rate, 4)
            """
        )
    )


def downgrade() -> None:
    for table in (
        "supplier_payments",
        "customer_payments",
        "delivery_notes",
        "goods_receipts",
    ):
        op.drop_column(table, "base_amount")
        op.drop_column(table, "foreign_amount")
