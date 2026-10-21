"""Ledger standalone flag and cost sheet journal charge type link.

Revision ID: d9e0f1a2b188
Revises: c8d9e0f1a187
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "d9e0f1a2b188"
down_revision: str | None = "c8d9e0f1a187"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "is_standalone_ledger",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "cost_sheet_journal_lines",
        sa.Column("charge_type_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_cost_sheet_journal_lines_charge_type_id",
        "cost_sheet_journal_lines",
        "charge_types",
        ["charge_type_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_cost_sheet_journal_lines_charge_type_id",
        "cost_sheet_journal_lines",
        ["charge_type_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cost_sheet_journal_lines_charge_type_id",
        table_name="cost_sheet_journal_lines",
    )
    op.drop_constraint(
        "fk_cost_sheet_journal_lines_charge_type_id",
        "cost_sheet_journal_lines",
        type_="foreignkey",
    )
    op.drop_column("cost_sheet_journal_lines", "charge_type_id")
    op.drop_column("accounts", "is_standalone_ledger")
