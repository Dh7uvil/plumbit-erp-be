"""Role record_scope for list filtering.

Revision ID: r1s2t3u4v567
Revises: p1q2r3s4t567
Create Date: 2026-09-29 23:52:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "r1s2t3u4v567"
down_revision: str | None = "p1q2r3s4t567"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "roles",
        sa.Column(
            "record_scope",
            sa.String(length=20),
            nullable=False,
            server_default="all",
        ),
    )


def downgrade() -> None:
    op.drop_column("roles", "record_scope")
