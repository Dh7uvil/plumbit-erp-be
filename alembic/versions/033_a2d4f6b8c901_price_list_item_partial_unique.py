"""Use partial uniqueness for active price-list items.

Revision ID: a2d4f6b8c901
Revises: f7c3a8e1b946
Create Date: 2026-09-15 13:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2d4f6b8c901"
down_revision: str | None = "f7c3a8e1b946"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_price_list_items_tenant_list_product",
        "price_list_items",
        type_="unique",
    )
    op.create_index(
        "uq_price_list_items_tenant_list_product_active",
        "price_list_items",
        ["tenant_id", "price_list_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_price_list_items_tenant_list_product_active",
        table_name="price_list_items",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_unique_constraint(
        "uq_price_list_items_tenant_list_product",
        "price_list_items",
        ["tenant_id", "price_list_id", "product_id"],
    )
