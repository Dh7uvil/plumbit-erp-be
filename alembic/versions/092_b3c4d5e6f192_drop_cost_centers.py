"""Drop cost center master and dimension columns.

Revision ID: b3c4d5e6f192
Revises: a2b3c4d5e191
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6f192"
down_revision: str | None = "a2b3c4d5e191"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("budget_lines_cost_center_id_fkey", "budget_lines", type_="foreignkey")
    op.drop_column("budget_lines", "cost_center_id")

    op.drop_constraint(
        "fk_journal_entry_lines_cost_center_id_cost_centers",
        "journal_entry_lines",
        type_="foreignkey",
    )
    op.drop_index("ix_journal_entry_lines_cost_center_id", table_name="journal_entry_lines")
    op.drop_column("journal_entry_lines", "cost_center_id")

    op.drop_constraint(
        "fk_journal_entries_cost_center_id_cost_centers",
        "journal_entries",
        type_="foreignkey",
    )
    op.drop_index("ix_journal_entries_cost_center_id", table_name="journal_entries")
    op.drop_column("journal_entries", "cost_center_id")

    op.drop_constraint("voucher_lines_cost_center_id_fkey", "voucher_lines", type_="foreignkey")
    op.drop_column("voucher_lines", "cost_center_id")

    op.drop_constraint("vouchers_cost_center_id_fkey", "vouchers", type_="foreignkey")
    op.drop_column("vouchers", "cost_center_id")

    op.drop_index("uq_cost_centers_tenant_id_code_active", table_name="cost_centers")
    op.drop_index("ix_cost_centers_tenant_id", table_name="cost_centers")
    op.drop_table("cost_centers")


def downgrade() -> None:
    raise NotImplementedError("Cost centers were removed from the product")
