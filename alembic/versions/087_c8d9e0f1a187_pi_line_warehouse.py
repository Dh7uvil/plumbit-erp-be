"""Add purchase_invoice_lines.warehouse_id.

Revision ID: c8d9e0f1a187
Revises: b7c8d9e0f186
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "c8d9e0f1a187"
down_revision: str | None = "b7c8d9e0f186"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "purchase_invoice_lines",
        sa.Column("warehouse_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_purchase_invoice_lines_warehouse_id",
        "purchase_invoice_lines",
        "warehouses",
        ["warehouse_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_purchase_invoice_lines_warehouse_id",
        "purchase_invoice_lines",
        ["warehouse_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_purchase_invoice_lines_warehouse_id", "purchase_invoice_lines")
    op.drop_constraint(
        "fk_purchase_invoice_lines_warehouse_id",
        "purchase_invoice_lines",
        type_="foreignkey",
    )
    op.drop_column("purchase_invoice_lines", "warehouse_id")
