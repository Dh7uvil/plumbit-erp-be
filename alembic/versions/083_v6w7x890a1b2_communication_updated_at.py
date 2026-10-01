"""Add updated_at to remaining communication extended tables.

Revision ID: v6w7x890a1b2
Revises: u5v6w7x890a1
Create Date: 2026-09-30 15:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "v6w7x890a1b2"
down_revision: str | None = "u5v6w7x890a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "chat_message_reads",
    "chat_message_reactions",
    "chat_message_mentions",
    "chat_message_attachments",
    "chat_pinned_messages",
    "chat_saved_messages",
)


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_column(table, "updated_at")
