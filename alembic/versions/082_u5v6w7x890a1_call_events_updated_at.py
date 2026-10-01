"""Add updated_at to call_events.

Revision ID: u5v6w7x890a1
Revises: t4u5v6w7x890
Create Date: 2026-09-30 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "u5v6w7x890a1"
down_revision: str | None = "t4u5v6w7x890"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "call_events",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("call_events", "updated_at")
