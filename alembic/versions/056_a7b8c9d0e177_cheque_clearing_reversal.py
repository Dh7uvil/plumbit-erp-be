"""Add clearing reversal journal reference on cheques.

Revision ID: a7b8c9d0e177
Revises: f6a7b8c9d066
Create Date: 2026-09-22 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7b8c9d0e177"
down_revision: str | None = "f6a7b8c9d066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "cheques",
        sa.Column(
            "clearing_reversal_journal_entry_id",
            UUID,
            sa.ForeignKey("journal_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("cheques", "clearing_reversal_journal_entry_id")
