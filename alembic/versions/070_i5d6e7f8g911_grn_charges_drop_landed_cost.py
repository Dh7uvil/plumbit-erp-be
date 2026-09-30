"""GRN charges, remove PO expense lines, drop landed cost tables.

Revision ID: i5d6e7f8g911
Revises: h4c5d6e7f810
Create Date: 2026-09-29 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "i5d6e7f8g911"
down_revision: str | None = "h4c5d6e7f810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
_MONEY = sa.Numeric(18, 4)
_QTY = sa.Numeric(18, 6)


def upgrade() -> None:
    op.create_table(
        "goods_receipt_charges",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("goods_receipt_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("charge_type_id", UUID, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", _MONEY, nullable=False),
        sa.Column("base_amount", _MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("allocation_basis", sa.String(length=20), nullable=True),
        sa.Column("supplier_id", UUID, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["charge_type_id"], ["charge_types.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["customers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "goods_receipt_id",
            "line_number",
            name="uq_goods_receipt_charges_header_line_number",
        ),
    )
    op.create_index(
        "ix_goods_receipt_charges_goods_receipt_id",
        "goods_receipt_charges",
        ["goods_receipt_id"],
    )
    op.create_index(
        "ix_goods_receipt_charges_charge_type_id",
        "goods_receipt_charges",
        ["charge_type_id"],
    )
    op.create_index(
        "ix_goods_receipt_charges_tenant_id",
        "goods_receipt_charges",
        ["tenant_id"],
    )

    op.add_column(
        "goods_receipt_lines",
        sa.Column(
            "allocated_charge_amount",
            _MONEY,
            server_default=sa.text("0"),
            nullable=False,
        ),
    )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    po_columns = {column["name"] for column in inspector.get_columns("purchase_order_lines")}
    if "line_type" in po_columns:
        expense_count = bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM purchase_order_lines WHERE line_type = 'EXPENSE'"
            )
        ).scalar_one()
        if expense_count:
            raise RuntimeError(
                "Cannot migrate: purchase orders contain EXPENSE charge lines. "
                "Remove or convert them before upgrading."
            )

    op.execute(
        sa.text(
            "ALTER TABLE purchase_order_lines "
            "DROP CONSTRAINT IF EXISTS fk_purchase_order_lines_charge_type_id"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE purchase_order_lines "
            "DROP CONSTRAINT IF EXISTS fk_purchase_order_lines_expense_account_id"
        )
    )
    op.execute(sa.text("DROP INDEX IF EXISTS ix_purchase_order_lines_charge_type_id"))
    for column in ("line_type", "expense_account_id", "expense_category", "charge_type_id"):
        op.execute(
            sa.text(f"ALTER TABLE purchase_order_lines DROP COLUMN IF EXISTS {column}")
        )

    op.execute(
        sa.text(
            "ALTER TABLE cost_sheets DROP CONSTRAINT IF EXISTS cost_sheets_landed_cost_id_fkey"
        )
    )
    op.execute(sa.text("ALTER TABLE cost_sheets DROP COLUMN IF EXISTS landed_cost_id"))

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("landed_cost_allocations"):
        op.drop_table("landed_cost_allocations")
    if inspector.has_table("landed_cost_charges"):
        op.drop_table("landed_cost_charges")
    if inspector.has_table("landed_costs"):
        op.drop_table("landed_costs")

    op.execute(
        sa.text("DELETE FROM attachments WHERE entity_type = 'landed_cost'")
    )
    op.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            WHERE permission_id IN (
                SELECT id FROM permissions WHERE resource = 'landed_cost'
            )
            """
        )
    )
    op.execute(sa.text("DELETE FROM permissions WHERE resource = 'landed_cost'"))
    op.execute(
        sa.text("DELETE FROM document_sequences WHERE document_type = 'LANDED_COST'")
    )


def downgrade() -> None:
    # IRREVERSIBLE: GRN charges and deleted landed-cost data cannot be restored from this migration.
    op.execute(
        sa.text(
            "INSERT INTO document_sequences (id, tenant_id, document_type, series, prefix, "
            "next_number, fiscal_year, created_at, updated_at) "
            "SELECT gen_random_uuid(), t.id, 'LANDED_COST', 'LC', 'LC', 1, "
            "EXTRACT(YEAR FROM CURRENT_DATE)::int, now(), now() FROM tenants t"
        )
    )

    op.create_table(
        "landed_costs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("document_number", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_posted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("allocation_method", sa.String(length=20), nullable=False),
        sa.Column("shipment_id", UUID, nullable=True),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("journal_entry_id", UUID, nullable=True),
        sa.Column("reversal_journal_entry_id", UUID, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", UUID, nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", UUID, nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "landed_cost_charges",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("landed_cost_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("purchase_invoice_id", UUID, nullable=False),
        sa.Column("purchase_invoice_line_id", UUID, nullable=False),
        sa.Column("expense_category", sa.String(length=30), nullable=False),
        sa.Column("bill_number", sa.String(length=40), nullable=False),
        sa.Column("amount", _MONEY, nullable=False),
        sa.Column("base_amount", _MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("charge_type_id", UUID, nullable=True),
        sa.Column("allocation_basis", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "landed_cost_allocations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("landed_cost_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("goods_receipt_id", UUID, nullable=False),
        sa.Column("goods_receipt_line_id", UUID, nullable=False),
        sa.Column("allocation_base", _MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("allocated_amount", _MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("qty_remaining_at_post", _QTY, nullable=True),
        sa.Column("qty_consumed_at_post", _QTY, nullable=True),
        sa.Column("previous_landed_unit_cost", _MONEY, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column("cost_sheets", sa.Column("landed_cost_id", UUID, nullable=True))

    op.add_column(
        "purchase_order_lines",
        sa.Column(
            "line_type",
            sa.String(length=30),
            server_default=sa.text("'PRODUCT'"),
            nullable=False,
        ),
    )
    op.add_column("purchase_order_lines", sa.Column("expense_account_id", UUID, nullable=True))
    op.add_column(
        "purchase_order_lines",
        sa.Column("expense_category", sa.String(length=30), nullable=True),
    )
    op.add_column("purchase_order_lines", sa.Column("charge_type_id", UUID, nullable=True))

    op.drop_column("goods_receipt_lines", "allocated_charge_amount")
    op.drop_table("goods_receipt_charges")
