"""Add gen_random_uuid() default for entry_books.id.

Revision ID: f5a6b7c8d084
Revises: e4f5a6b7c083
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f5a6b7c8d084"
down_revision: str | None = "e4f5a6b7c083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "entry_books",
        "id",
        server_default=sa.text("gen_random_uuid()"),
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "entry_books",
        "id",
        server_default=None,
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        existing_nullable=False,
    )
