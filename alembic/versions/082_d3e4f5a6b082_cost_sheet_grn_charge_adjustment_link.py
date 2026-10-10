"""Link cost sheets to GRN charge adjustments from journal capitalize.

Revision ID: d3e4f5a6b082
Revises: c2d3e4f5a081
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d3e4f5a6b082"
down_revision: str | None = "c2d3e4f5a081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "cost_sheets",
        sa.Column("goods_receipt_charge_adjustment_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_cost_sheets_grn_charge_adjustment_id",
        "cost_sheets",
        "goods_receipt_charge_adjustments",
        ["goods_receipt_charge_adjustment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_cost_sheets_goods_receipt_charge_adjustment_id",
        "cost_sheets",
        ["goods_receipt_charge_adjustment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cost_sheets_goods_receipt_charge_adjustment_id", table_name="cost_sheets")
    op.drop_constraint(
        "fk_cost_sheets_grn_charge_adjustment_id",
        "cost_sheets",
        type_="foreignkey",
    )
    op.drop_column("cost_sheets", "goods_receipt_charge_adjustment_id")
