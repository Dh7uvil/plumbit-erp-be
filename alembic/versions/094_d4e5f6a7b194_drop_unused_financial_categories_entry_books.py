"""Drop unused financial categories and entry books masters.

Revision ID: d4e5f6a7b194
Revises: c3d4e5f6a193
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "d4e5f6a7b194"
down_revision: str | None = "c3d4e5f6a193"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM permissions WHERE module = 'accounting' AND resource = 'financial_category'"
        )
    )
    op.drop_constraint("fk_accounts_financial_category_id", "accounts", type_="foreignkey")
    op.drop_column("accounts", "financial_category_id")
    op.drop_index("ix_financial_categories_tenant_id", table_name="financial_categories")
    op.drop_table("financial_categories")
    op.drop_table("entry_books")


def downgrade() -> None:
    op.create_table(
        "entry_books",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            UUID,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("voucher_type", sa.String(30), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("series_prefix", sa.String(20), nullable=False),
        sa.Column("default_account_id", UUID, nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint("tenant_id", "voucher_type", name="uq_entry_books_tenant_type"),
    )
    op.create_table(
        "financial_categories",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "tenant_id",
            UUID,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("account_type", sa.String(30), nullable=False),
        sa.Column("account_subtype", sa.String(30), nullable=True),
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
        sa.UniqueConstraint("tenant_id", "name", name="uq_financial_categories_tenant_name"),
    )
    op.create_index("ix_financial_categories_tenant_id", "financial_categories", ["tenant_id"])
    op.add_column("accounts", sa.Column("financial_category_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_accounts_financial_category_id",
        "accounts",
        "financial_categories",
        ["financial_category_id"],
        ["id"],
        ondelete="SET NULL",
    )
