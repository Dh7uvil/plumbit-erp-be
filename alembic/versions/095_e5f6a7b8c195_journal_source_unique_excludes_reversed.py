"""Allow reposting after reversal: exclude reversed journals from source unique index.

Revision ID: e5f6a7b8c195
Revises: d4e5f6a7b194
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c195"
down_revision: str | None = "d4e5f6a7b194"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WHERE = (
    "status = 'POSTED' AND deleted_at IS NULL "
    "AND source_type IS NOT NULL AND source_id IS NOT NULL "
    "AND reversed_by_id IS NULL"
)


def upgrade() -> None:
    op.drop_index("uq_journal_entries_tenant_source_posted", table_name="journal_entries")
    op.create_index(
        "uq_journal_entries_tenant_source_posted",
        "journal_entries",
        ["tenant_id", "source_type", "source_id"],
        unique=True,
        postgresql_where=sa.text(_WHERE),
    )


def downgrade() -> None:
    op.drop_index("uq_journal_entries_tenant_source_posted", table_name="journal_entries")
    op.create_index(
        "uq_journal_entries_tenant_source_posted",
        "journal_entries",
        ["tenant_id", "source_type", "source_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'POSTED' AND deleted_at IS NULL "
            "AND source_type IS NOT NULL AND source_id IS NOT NULL"
        ),
    )
