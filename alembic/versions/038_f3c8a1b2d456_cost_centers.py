"""Cost centers master and journal dimension columns.

Revision ID: f3c8a1b2d456
Revises: e8b2d4f0c157
Create Date: 2026-09-21 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f3c8a1b2d456"
down_revision: str | None = "e8b2d4f0c157"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "cost_centers",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cost_centers_tenant_id", "cost_centers", ["tenant_id"], unique=False)
    op.create_index(
        "uq_cost_centers_tenant_id_code_active",
        "cost_centers",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.add_column(
        "journal_entries",
        sa.Column("cost_center_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_journal_entries_cost_center_id_cost_centers",
        "journal_entries",
        "cost_centers",
        ["cost_center_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_journal_entries_cost_center_id",
        "journal_entries",
        ["cost_center_id"],
        unique=False,
    )

    op.add_column(
        "journal_entry_lines",
        sa.Column("cost_center_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_journal_entry_lines_cost_center_id_cost_centers",
        "journal_entry_lines",
        "cost_centers",
        ["cost_center_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_journal_entry_lines_cost_center_id",
        "journal_entry_lines",
        ["cost_center_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_journal_entry_lines_cost_center_id", table_name="journal_entry_lines")
    op.drop_constraint(
        "fk_journal_entry_lines_cost_center_id_cost_centers",
        "journal_entry_lines",
        type_="foreignkey",
    )
    op.drop_column("journal_entry_lines", "cost_center_id")

    op.drop_index("ix_journal_entries_cost_center_id", table_name="journal_entries")
    op.drop_constraint(
        "fk_journal_entries_cost_center_id_cost_centers",
        "journal_entries",
        type_="foreignkey",
    )
    op.drop_column("journal_entries", "cost_center_id")

    op.drop_index("uq_cost_centers_tenant_id_code_active", table_name="cost_centers")
    op.drop_index("ix_cost_centers_tenant_id", table_name="cost_centers")
    op.drop_table("cost_centers")
