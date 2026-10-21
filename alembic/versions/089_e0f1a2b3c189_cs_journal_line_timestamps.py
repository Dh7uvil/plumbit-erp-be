"""Add timestamps to cost sheet journal lines (ORM parity).

Revision ID: e0f1a2b3c189
Revises: d9e0f1a2b188
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e0f1a2b3c189"
down_revision: str | None = "d9e0f1a2b188"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "cost_sheet_journal_lines",
        "id",
        server_default=sa.text("gen_random_uuid()"),
    )
    op.add_column(
        "cost_sheet_journal_lines",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "cost_sheet_journal_lines",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_column("cost_sheet_journal_lines", "updated_at")
    op.drop_column("cost_sheet_journal_lines", "created_at")
