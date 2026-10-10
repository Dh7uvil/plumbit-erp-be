"""Backfill GP/PV document sequences and entry books for existing tenants.

Revision ID: e4f5a6b7c083
Revises: d3e4f5a6b082
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4f5a6b7c083"
down_revision: str | None = "d3e4f5a6b082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENTRY_BOOKS = (
    ("GENERAL_PURCHASE", "General Purchase", "GP"),
    ("PAYMENT_VOUCHER", "Payment Voucher", "PV"),
)

_DOCUMENT_SEQUENCES = (
    ("GENERAL_PURCHASE_VOUCHER", "GP"),
    ("PAYMENT_VOUCHER", "PV"),
)


def upgrade() -> None:
    for voucher_type, name, prefix in _ENTRY_BOOKS:
        op.execute(
            sa.text(
                """
                INSERT INTO entry_books (
                    id, tenant_id, voucher_type, name, series_prefix, is_active
                )
                SELECT gen_random_uuid(), t.id, :voucher_type, :name, :prefix, true
                FROM tenants t
                WHERE NOT EXISTS (
                    SELECT 1 FROM entry_books eb
                    WHERE eb.tenant_id = t.id AND eb.voucher_type = :voucher_type
                )
                """
            ).bindparams(
                voucher_type=voucher_type,
                name=name,
                prefix=prefix,
            )
        )

    for document_type, series in _DOCUMENT_SEQUENCES:
        op.execute(
            sa.text(
                """
                INSERT INTO document_sequences (
                    id, tenant_id, document_type, series, fiscal_year, prefix, padding,
                    next_number, is_active, created_at, updated_at
                )
                SELECT gen_random_uuid(), t.id, :document_type, :series,
                    EXTRACT(YEAR FROM CURRENT_DATE)::int, :series, 6, 1, true, now(), now()
                FROM tenants t
                WHERE NOT EXISTS (
                    SELECT 1 FROM document_sequences ds
                    WHERE ds.tenant_id = t.id
                      AND ds.document_type = :document_type
                      AND ds.deleted_at IS NULL
                )
                """
            ).bindparams(document_type=document_type, series=series)
        )


def downgrade() -> None:
    for document_type, _series in _DOCUMENT_SEQUENCES:
        op.execute(
            sa.text(
                """
                DELETE FROM document_sequences
                WHERE document_type = :document_type
                  AND next_number = 1
                """
            ).bindparams(document_type=document_type)
        )
    for voucher_type, _name, _prefix in _ENTRY_BOOKS:
        op.execute(
            sa.text(
                "DELETE FROM entry_books WHERE voucher_type = :voucher_type"
            ).bindparams(voucher_type=voucher_type)
        )
