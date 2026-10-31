"""Sales documents: line warehouse/loc, remarks, fiscal period override.

Revision ID: c3d4e5f6a193
Revises: b3c4d5e6f192
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "c3d4e5f6a193"
down_revision: str | None = "b3c4d5e6f192"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINE_TABLES = (
    "quotation_lines",
    "sales_order_lines",
    "sales_invoice_lines",
)
_HEADER_TABLES = (
    "quotations",
    "sales_orders",
    "sales_invoices",
)
_REMARKS_TABLES = (
    "quotation_lines",
    "sales_order_lines",
)


def _add_line_warehouse(table: str) -> None:
    op.add_column(table, sa.Column("warehouse_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        f"fk_{table}_warehouse_id",
        table,
        "warehouses",
        ["warehouse_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(f"ix_{table}_warehouse_id", table, ["warehouse_id"])


def _drop_line_warehouse(table: str) -> None:
    op.drop_index(f"ix_{table}_warehouse_id", table_name=table)
    op.drop_constraint(f"fk_{table}_warehouse_id", table, type_="foreignkey")
    op.drop_column(table, "warehouse_id")


def upgrade() -> None:
    for table in _LINE_TABLES:
        _add_line_warehouse(table)
    for table in _REMARKS_TABLES:
        op.add_column(table, sa.Column("remarks", sa.Text(), nullable=True))
    for table in _HEADER_TABLES:
        op.add_column(table, sa.Column("fiscal_period", sa.Integer(), nullable=True))


def downgrade() -> None:
    for table in reversed(_HEADER_TABLES):
        op.drop_column(table, "fiscal_period")
    for table in reversed(_REMARKS_TABLES):
        op.drop_column(table, "remarks")
    for table in reversed(_LINE_TABLES):
        _drop_line_warehouse(table)
