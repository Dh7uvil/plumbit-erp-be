"""Cost sheet journal lines and stock transfer parity fields.

Revision ID: c2d3e4f5a081
Revises: a1b2c3d4e080
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c2d3e4f5a081"
down_revision: str | None = "a1b2c3d4e080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
_MONEY = sa.Numeric(18, 4)


def upgrade() -> None:
    op.add_column(
        "cost_sheets",
        sa.Column("journal_entry_id", UUID, nullable=True),
    )
    op.add_column(
        "cost_sheets",
        sa.Column("reversal_journal_entry_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_cost_sheets_journal_entry_id",
        "cost_sheets",
        "journal_entries",
        ["journal_entry_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_cost_sheets_reversal_journal_entry_id",
        "cost_sheets",
        "journal_entries",
        ["reversal_journal_entry_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "cost_sheet_journal_lines",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "tenant_id",
            UUID,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cost_sheet_id",
            UUID,
            sa.ForeignKey("cost_sheets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("line_kind", sa.String(1), nullable=False, server_default=sa.text("'G'")),
        sa.Column("account_id", UUID, sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True),
        sa.Column(
            "party_id",
            UUID,
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("debit", _MONEY, nullable=False, server_default=sa.text("0")),
        sa.Column("credit", _MONEY, nullable=False, server_default=sa.text("0")),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("capitalize", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint(
            "cost_sheet_id",
            "line_number",
            name="uq_cost_sheet_journal_lines_header_line",
        ),
    )
    op.create_index(
        "ix_cost_sheet_journal_lines_cost_sheet_id",
        "cost_sheet_journal_lines",
        ["cost_sheet_id"],
    )

    op.add_column("stock_transfers", sa.Column("reference_date", sa.Date(), nullable=True))
    op.add_column(
        "stock_transfers",
        sa.Column("reference_stock_transfer_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_stock_transfers_reference_stock_transfer_id",
        "stock_transfers",
        "stock_transfers",
        ["reference_stock_transfer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "stock_transfer_lines",
        sa.Column("reservation_number", sa.String(80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stock_transfer_lines", "reservation_number")
    op.drop_constraint(
        "fk_stock_transfers_reference_stock_transfer_id",
        "stock_transfers",
        type_="foreignkey",
    )
    op.drop_column("stock_transfers", "reference_stock_transfer_id")
    op.drop_column("stock_transfers", "reference_date")
    op.drop_table("cost_sheet_journal_lines")
    op.drop_constraint("fk_cost_sheets_reversal_journal_entry_id", "cost_sheets", type_="foreignkey")
    op.drop_constraint("fk_cost_sheets_journal_entry_id", "cost_sheets", type_="foreignkey")
    op.drop_column("cost_sheets", "reversal_journal_entry_id")
    op.drop_column("cost_sheets", "journal_entry_id")
