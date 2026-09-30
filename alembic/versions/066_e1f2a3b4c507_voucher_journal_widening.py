"""Widen vouchers for journal entry book and add line debit/credit.

Revision ID: e1f2a3b4c507
Revises: d0e1f2a3b406
Create Date: 2026-09-29 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1f2a3b4c507"
down_revision: str | None = "d0e1f2a3b406"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONEY = sa.Numeric(18, 4)


def upgrade() -> None:
    op.add_column("vouchers", sa.Column("cheque_number", sa.String(length=50), nullable=True))
    op.add_column("vouchers", sa.Column("cheque_date", sa.Date(), nullable=True))
    op.add_column("vouchers", sa.Column("external_reference", sa.String(length=100), nullable=True))
    op.alter_column("vouchers", "payment_account_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column("vouchers", "payment_method", existing_type=sa.String(length=30), nullable=True)

    op.add_column(
        "voucher_lines",
        sa.Column("debit", _MONEY, server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "voucher_lines",
        sa.Column("credit", _MONEY, server_default=sa.text("0"), nullable=False),
    )

    # Backfill debit/credit from amount and parent voucher_type.
    op.execute(
        """
        UPDATE voucher_lines vl
        SET
            debit = CASE
                WHEN v.voucher_type IN ('CASH_PAYMENT', 'BANK_PAYMENT', 'CONTRA')
                THEN vl.amount
                ELSE 0
            END,
            credit = CASE
                WHEN v.voucher_type IN ('CASH_RECEIPT', 'BANK_RECEIPT')
                THEN vl.amount
                ELSE 0
            END
        FROM vouchers v
        WHERE vl.voucher_id = v.id
        """
    )

    op.add_column(
        "journal_entries",
        sa.Column("external_reference", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("journal_entries", "external_reference")
    op.drop_column("voucher_lines", "credit")
    op.drop_column("voucher_lines", "debit")
    op.alter_column("vouchers", "payment_method", existing_type=sa.String(length=30), nullable=False)
    op.alter_column("vouchers", "payment_account_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("vouchers", "external_reference")
    op.drop_column("vouchers", "cheque_date")
    op.drop_column("vouchers", "cheque_number")
