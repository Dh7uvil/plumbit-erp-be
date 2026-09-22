"""Wire charge types into documents and add volume / export fields.

Revision ID: c9f2a5b3d021
Revises: b8e1f4a2c020
Create Date: 2026-09-22 12:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c9f2a5b3d021"
down_revision: str | None = "b8e1f4a2c020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
_QTY = sa.Numeric(18, 6)


def upgrade() -> None:
    op.add_column(
        "purchase_invoice_lines",
        sa.Column("charge_type_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_purchase_invoice_lines_charge_type_id_charge_types",
        "purchase_invoice_lines",
        "charge_types",
        ["charge_type_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_purchase_invoice_lines_charge_type_id",
        "purchase_invoice_lines",
        ["charge_type_id"],
        unique=False,
    )

    op.add_column(
        "landed_cost_charges",
        sa.Column("charge_type_id", UUID, nullable=True),
    )
    op.add_column(
        "landed_cost_charges",
        sa.Column("allocation_basis", sa.String(length=20), nullable=True),
    )
    op.create_foreign_key(
        "fk_landed_cost_charges_charge_type_id_charge_types",
        "landed_cost_charges",
        "charge_types",
        ["charge_type_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_landed_cost_charges_charge_type_id",
        "landed_cost_charges",
        ["charge_type_id"],
        unique=False,
    )

    op.add_column("products", sa.Column("volume", _QTY, nullable=True))
    op.add_column("goods_receipt_lines", sa.Column("volume", _QTY, nullable=True))

    op.add_column(
        "sales_invoices",
        sa.Column("country_of_origin", sa.String(length=2), nullable=True),
    )
    op.add_column(
        "sales_invoice_lines",
        sa.Column("hs_code", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "credit_notes",
        sa.Column("country_of_origin", sa.String(length=2), nullable=True),
    )
    op.add_column(
        "credit_note_lines",
        sa.Column("hs_code", sa.String(length=20), nullable=True),
    )

    op.execute(
        sa.text(
            """
            UPDATE purchase_invoice_lines pil
            SET charge_type_id = ct.id
            FROM charge_types ct
            WHERE pil.tenant_id = ct.tenant_id
              AND ct.deleted_at IS NULL
              AND pil.expense_category IS NOT NULL
              AND pil.line_type = 'EXPENSE'
              AND ct.code = CASE pil.expense_category
                WHEN 'FREIGHT' THEN 'FREIGHT'
                WHEN 'CUSTOMS_DUTY' THEN 'CUSTOMS_DUTY'
                WHEN 'INSURANCE' THEN 'INSURANCE'
                WHEN 'CLEARING' THEN 'CUSTOMS_CLEARANCE'
                WHEN 'INSPECTION' THEN 'INSPECTION'
                ELSE 'OTHER_CHARGES'
              END
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE landed_cost_charges lcc
            SET charge_type_id = pil.charge_type_id
            FROM purchase_invoice_lines pil
            WHERE lcc.purchase_invoice_line_id = pil.id
              AND lcc.tenant_id = pil.tenant_id
              AND pil.charge_type_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_column("credit_note_lines", "hs_code")
    op.drop_column("credit_notes", "country_of_origin")
    op.drop_column("sales_invoice_lines", "hs_code")
    op.drop_column("sales_invoices", "country_of_origin")
    op.drop_column("goods_receipt_lines", "volume")
    op.drop_column("products", "volume")
    op.drop_index("ix_landed_cost_charges_charge_type_id", table_name="landed_cost_charges")
    op.drop_constraint(
        "fk_landed_cost_charges_charge_type_id_charge_types",
        "landed_cost_charges",
        type_="foreignkey",
    )
    op.drop_column("landed_cost_charges", "allocation_basis")
    op.drop_column("landed_cost_charges", "charge_type_id")
    op.drop_index("ix_purchase_invoice_lines_charge_type_id", table_name="purchase_invoice_lines")
    op.drop_constraint(
        "fk_purchase_invoice_lines_charge_type_id_charge_types",
        "purchase_invoice_lines",
        type_="foreignkey",
    )
    op.drop_column("purchase_invoice_lines", "charge_type_id")
