"""Add users.token_version for JWT revocation.

Revision ID: k7f8g9h0i123
Revises: j6e7f8g9h012
Create Date: 2026-09-29 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "k7f8g9h0i123"
down_revision: str | None = "j6e7f8g9h012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
