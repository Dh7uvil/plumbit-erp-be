"""Document sequence for OTHER cost sheets.

Revision ID: c3d4e5f6a033
Revises: b2c3d4e5f032
Create Date: 2026-09-22 14:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3d4e5f6a033"
down_revision: str | None = "b2c3d4e5f032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO document_sequences (
            id, tenant_id, document_type, series, fiscal_year, prefix, next_number, padding, is_active, created_at, updated_at
        )
        SELECT gen_random_uuid(), t.id, 'COST_SHEET_OTHER', 'CSO', EXTRACT(YEAR FROM CURRENT_DATE)::int, 'CSO', 1, 6, true, now(), now()
        FROM tenants t
        WHERE NOT EXISTS (
            SELECT 1 FROM document_sequences ds
            WHERE ds.tenant_id = t.id AND ds.document_type = 'COST_SHEET_OTHER' AND ds.deleted_at IS NULL
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE document_sequences
        SET deleted_at = now()
        WHERE document_type = 'COST_SHEET_OTHER' AND deleted_at IS NULL
        """
    )
