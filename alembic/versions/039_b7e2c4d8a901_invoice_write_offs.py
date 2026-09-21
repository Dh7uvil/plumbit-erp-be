"""Invoice write-offs and bad debt expense role.

Revision ID: b7e2c4d8a901
Revises: f3c8a1b2d456
Create Date: 2026-09-21 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b7e2c4d8a901"
down_revision: str | None = "f3c8a1b2d456"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
_MONEY = sa.Numeric(19, 4)


def upgrade() -> None:
    op.add_column(
        "sales_invoices",
        sa.Column("amount_written_off", _MONEY, server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "purchase_invoices",
        sa.Column("amount_written_off", _MONEY, server_default=sa.text("0"), nullable=False),
    )

    op.create_table(
        "invoice_write_offs",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("document_kind", sa.String(length=40), nullable=False),
        sa.Column("invoice_id", UUID, nullable=False),
        sa.Column("amount", _MONEY, nullable=False),
        sa.Column("write_off_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("expense_account_id", UUID, nullable=True),
        sa.Column("journal_entry_id", UUID, nullable=True),
        sa.Column("reversal_journal_entry_id", UUID, nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
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
        sa.ForeignKeyConstraint(["expense_account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reversal_journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_invoice_write_offs_tenant_invoice",
        "invoice_write_offs",
        ["tenant_id", "document_kind", "invoice_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_invoice_write_offs_tenant_invoice", table_name="invoice_write_offs")
    op.drop_table("invoice_write_offs")
    op.drop_column("purchase_invoices", "amount_written_off")
    op.drop_column("sales_invoices", "amount_written_off")
