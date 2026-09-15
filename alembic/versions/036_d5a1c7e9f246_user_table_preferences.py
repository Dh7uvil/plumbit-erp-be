"""User table column preferences.

Revision ID: d5a1c7e9f246
Revises: c4f8a0d2e135
Create Date: 2026-09-15 16:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d5a1c7e9f246"
down_revision: str | None = "c4f8a0d2e135"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "user_table_preferences",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("table_key", sa.String(length=100), nullable=False),
        sa.Column("visible_columns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("column_order", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "table_key",
            name="uq_user_table_preferences_tenant_user_table",
        ),
    )
    op.create_index(
        "ix_user_table_preferences_tenant_id",
        "user_table_preferences",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_table_preferences_user_id",
        "user_table_preferences",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_user_table_preferences_user_id", table_name="user_table_preferences")
    op.drop_index("ix_user_table_preferences_tenant_id", table_name="user_table_preferences")
    op.drop_table("user_table_preferences")
