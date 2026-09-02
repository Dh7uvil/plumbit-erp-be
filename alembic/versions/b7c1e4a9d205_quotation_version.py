"""add quotation version for optimistic concurrency

Revision ID: b7c1e4a9d205
Revises: a9f2d6e3b718
Create Date: 2026-09-02 09:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c1e4a9d205"
down_revision: str | Sequence[str] | None = "a9f2d6e3b718"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add optimistic-concurrency version on quotations."""

    op.add_column(
        "quotations",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )


def downgrade() -> None:
    """Drop quotations.version."""

    op.drop_column("quotations", "version")
