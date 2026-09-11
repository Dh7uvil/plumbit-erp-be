"""FIFO costing, goods receipts, and quality inspections.

Revision ID: f0c1d5e8a247
Revises: e9b4c0d3f126
Create Date: 2026-09-09 21:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "f0c1d5e8a247"
down_revision: str | Sequence[str] | None = "e9b4c0d3f126"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
QTY = sa.Numeric(18, 6)
MONEY = sa.Numeric(18, 4)


def _pk() -> sa.Column:
    return sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False)


def _tenant() -> sa.Column:
    return sa.Column("tenant_id", UUID, nullable=False)


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def _soft_delete() -> sa.Column:
    return sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)


def _audit_users() -> list[sa.Column]:
    return [
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
    ]


def upgrade() -> None:
    """Apply this revision."""
    _add_shared_columns()
    _create_costing_tables()
    _create_goods_receipt_tables()
    _create_quality_inspection_tables()
    _backfill_estimated_layers()
    _backfill_catalog_permissions()


def _add_shared_columns() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "costing_method",
            sa.String(length=30),
            server_default=sa.text("'FIFO'"),
            nullable=False,
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "allow_over_receipt",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("over_receipt_tolerance_pct", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "qc_required_default",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "requires_qc",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "stock_balances",
        sa.Column("qty_quality_hold", QTY, server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        "ck_stock_balances_qty_quality_hold_non_negative",
        "stock_balances",
        "qty_quality_hold >= 0",
    )
    op.add_column("stock_movements", sa.Column("unit_cost", MONEY, nullable=True))
    op.add_column("stock_movements", sa.Column("value", MONEY, nullable=True))
    op.add_column(
        "stock_movements",
        sa.Column(
            "is_estimated_cost",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column("stock_adjustment_lines", sa.Column("unit_cost", MONEY, nullable=True))


def _create_costing_tables() -> None:
    op.create_table(
        "stock_cost_layers",
        _pk(),
        _tenant(),
        sa.Column("warehouse_id", UUID, nullable=False),
        sa.Column("product_id", UUID, nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", UUID, nullable=False),
        sa.Column("source_line_id", UUID, nullable=True),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("qty_received", QTY, nullable=False),
        sa.Column("qty_remaining", QTY, nullable=False),
        sa.Column("unit_cost", MONEY, nullable=False),
        sa.Column("landed_unit_cost", MONEY, nullable=False),
        sa.Column("is_estimated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_negative", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_cost_layers_tenant_id", "stock_cost_layers", ["tenant_id"])
    op.create_index("ix_stock_cost_layers_warehouse_id", "stock_cost_layers", ["warehouse_id"])
    op.create_index("ix_stock_cost_layers_product_id", "stock_cost_layers", ["product_id"])
    op.create_index(
        "ix_stock_cost_layers_fifo",
        "stock_cost_layers",
        ["tenant_id", "product_id", "warehouse_id", "document_date", "created_at"],
    )
    op.create_index(
        "ix_stock_cost_layers_tenant_source",
        "stock_cost_layers",
        ["tenant_id", "source_type", "source_id"],
    )

    op.create_table(
        "stock_cost_consumptions",
        _pk(),
        _tenant(),
        sa.Column("movement_id", UUID, nullable=False),
        sa.Column("layer_id", UUID, nullable=False),
        sa.Column("qty", QTY, nullable=False),
        sa.Column("unit_cost", MONEY, nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["movement_id"], ["stock_movements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["layer_id"], ["stock_cost_layers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stock_cost_consumptions_tenant_id", "stock_cost_consumptions", ["tenant_id"]
    )
    op.create_index(
        "ix_stock_cost_consumptions_movement_id", "stock_cost_consumptions", ["movement_id"]
    )
    op.create_index("ix_stock_cost_consumptions_layer_id", "stock_cost_consumptions", ["layer_id"])


def _create_goods_receipt_tables() -> None:
    op.create_table(
        "goods_receipts",
        _pk(),
        _tenant(),
        sa.Column("document_number", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_posted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("supplier_id", UUID, nullable=False),
        sa.Column("warehouse_id", UUID, nullable=False),
        sa.Column("purchase_order_id", UUID, nullable=True),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("tax_treatment", sa.String(length=30), nullable=False),
        sa.Column("place_of_supply", sa.String(length=30), nullable=False),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("base_currency_id", UUID, nullable=False),
        sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=False),
        sa.Column("supplier_invoice_number", sa.String(length=80), nullable=True),
        sa.Column("delivery_challan_number", sa.String(length=80), nullable=True),
        sa.Column("bill_of_entry_number", sa.String(length=80), nullable=True),
        sa.Column("bill_of_entry_date", sa.Date(), nullable=True),
        sa.Column("container_number", sa.String(length=80), nullable=True),
        sa.Column("bl_number", sa.String(length=80), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "qc_status",
            sa.String(length=30),
            server_default=sa.text("'NOT_REQUIRED'"),
            nullable=False,
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", UUID, nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", UUID, nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["base_currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_goods_receipts_tenant_id", "goods_receipts", ["tenant_id"])
    op.create_index("ix_goods_receipts_supplier_id", "goods_receipts", ["supplier_id"])
    op.create_index("ix_goods_receipts_warehouse_id", "goods_receipts", ["warehouse_id"])
    op.create_index("ix_goods_receipts_branch_id", "goods_receipts", ["branch_id"])
    op.create_index("ix_goods_receipts_purchase_order_id", "goods_receipts", ["purchase_order_id"])
    op.create_index("ix_goods_receipts_tenant_id_status", "goods_receipts", ["tenant_id", "status"])
    op.create_index(
        "ix_goods_receipts_tenant_id_document_date",
        "goods_receipts",
        ["tenant_id", "document_date"],
    )
    op.create_index(
        "ix_goods_receipts_tenant_id_supplier_id",
        "goods_receipts",
        ["tenant_id", "supplier_id"],
    )
    op.create_index(
        "uq_goods_receipts_tenant_id_document_number_active",
        "goods_receipts",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "goods_receipt_lines",
        _pk(),
        _tenant(),
        sa.Column("goods_receipt_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("purchase_order_line_id", UUID, nullable=True),
        sa.Column("product_id", UUID, nullable=True),
        sa.Column("supplier_product_id", UUID, nullable=True),
        sa.Column("supplier_sku", sa.String(length=80), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", QTY, nullable=False),
        sa.Column("unit_id", UUID, nullable=True),
        sa.Column("rate", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("net_weight", QTY, nullable=True),
        sa.Column("gross_weight", QTY, nullable=True),
        sa.Column("qty_accepted", QTY, server_default=sa.text("0"), nullable=False),
        sa.Column("qty_rejected", QTY, server_default=sa.text("0"), nullable=False),
        sa.Column("qty_on_hold", QTY, server_default=sa.text("0"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["purchase_order_line_id"], ["purchase_order_lines.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["supplier_product_id"], ["supplier_products.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "goods_receipt_id",
            "line_number",
            name="uq_goods_receipt_lines_header_line_number",
        ),
    )
    op.create_index("ix_goods_receipt_lines_tenant_id", "goods_receipt_lines", ["tenant_id"])
    op.create_index(
        "ix_goods_receipt_lines_goods_receipt_id", "goods_receipt_lines", ["goods_receipt_id"]
    )
    op.create_index(
        "ix_goods_receipt_lines_purchase_order_line_id",
        "goods_receipt_lines",
        ["purchase_order_line_id"],
    )
    op.create_index("ix_goods_receipt_lines_product_id", "goods_receipt_lines", ["product_id"])


def _create_quality_inspection_tables() -> None:
    op.create_table(
        "quality_inspections",
        _pk(),
        _tenant(),
        sa.Column("document_number", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("goods_receipt_id", UUID, nullable=False),
        sa.Column("inspection_date", sa.Date(), nullable=False),
        sa.Column("inspector_user_id", UUID, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", UUID, nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", UUID, nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inspector_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quality_inspections_tenant_id", "quality_inspections", ["tenant_id"])
    op.create_index(
        "ix_quality_inspections_goods_receipt_id", "quality_inspections", ["goods_receipt_id"]
    )
    op.create_index(
        "ix_quality_inspections_tenant_id_status",
        "quality_inspections",
        ["tenant_id", "status"],
    )
    op.create_index(
        "uq_quality_inspections_tenant_id_document_number_active",
        "quality_inspections",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "quality_inspection_lines",
        _pk(),
        _tenant(),
        sa.Column("quality_inspection_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("goods_receipt_line_id", UUID, nullable=False),
        sa.Column("qty_inspected", QTY, nullable=False),
        sa.Column("qty_accepted", QTY, server_default=sa.text("0"), nullable=False),
        sa.Column("qty_rejected", QTY, server_default=sa.text("0"), nullable=False),
        sa.Column("qty_rework", QTY, server_default=sa.text("0"), nullable=False),
        sa.Column("disposition", sa.String(length=30), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["quality_inspection_id"], ["quality_inspections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["goods_receipt_line_id"], ["goods_receipt_lines.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "quality_inspection_id",
            "line_number",
            name="uq_quality_inspection_lines_header_line_number",
        ),
        sa.UniqueConstraint(
            "quality_inspection_id",
            "goods_receipt_line_id",
            name="uq_quality_inspection_lines_header_grn_line",
        ),
    )
    op.create_index(
        "ix_quality_inspection_lines_tenant_id", "quality_inspection_lines", ["tenant_id"]
    )
    op.create_index(
        "ix_quality_inspection_lines_quality_inspection_id",
        "quality_inspection_lines",
        ["quality_inspection_id"],
    )


def _backfill_estimated_layers() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO stock_cost_layers (
                tenant_id,
                warehouse_id,
                product_id,
                source_type,
                source_id,
                document_date,
                qty_received,
                qty_remaining,
                unit_cost,
                landed_unit_cost,
                is_estimated,
                is_negative
            )
            SELECT
                b.tenant_id,
                b.warehouse_id,
                b.product_id,
                'opening_estimated',
                b.id,
                COALESCE(b.last_movement_at::date, CURRENT_DATE),
                b.qty_on_hand,
                b.qty_on_hand,
                COALESCE(p.purchase_rate, 0),
                COALESCE(p.purchase_rate, 0),
                true,
                b.qty_on_hand < 0
            FROM stock_balances b
            JOIN products p ON p.id = b.product_id
            WHERE b.qty_on_hand <> 0
              AND NOT EXISTS (
                SELECT 1
                FROM stock_cost_layers l
                WHERE l.tenant_id = b.tenant_id
                  AND l.warehouse_id = b.warehouse_id
                  AND l.product_id = b.product_id
              )
            """
        )
    )


def _backfill_catalog_permissions() -> None:
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    catalog = parsed_catalog_permissions()

    for (tenant_id,) in tenants:
        existing = bind.execute(
            sa.text(
                "SELECT module, resource, action FROM permissions WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).fetchall()
        existing_keys = {(row.module, row.resource, row.action) for row in existing}
        for parsed in catalog:
            key = (parsed.module, parsed.resource, parsed.action)
            if key in existing_keys:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO permissions (tenant_id, module, resource, action)
                    VALUES (:tenant_id, :module, :resource, :action)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "module": parsed.module,
                    "resource": parsed.resource,
                    "action": parsed.action,
                },
            )

        admin = bind.execute(
            sa.text(
                """
                SELECT id FROM roles
                WHERE tenant_id = :tenant_id
                  AND is_system_role = true
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if admin is not None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO role_permissions (tenant_id, role_id, permission_id)
                    SELECT :tenant_id, :role_id, p.id
                    FROM permissions p
                    WHERE p.tenant_id = :tenant_id
                      AND NOT EXISTS (
                        SELECT 1
                        FROM role_permissions rp
                        WHERE rp.tenant_id = :tenant_id
                          AND rp.role_id = :role_id
                          AND rp.permission_id = p.id
                      )
                    """
                ),
                {"tenant_id": tenant_id, "role_id": admin.id},
            )


def downgrade() -> None:
    """Revert this revision."""
    op.drop_table("quality_inspection_lines")
    op.drop_table("quality_inspections")
    op.drop_table("goods_receipt_lines")
    op.drop_table("goods_receipts")
    op.drop_table("stock_cost_consumptions")
    op.drop_table("stock_cost_layers")
    op.drop_column("stock_adjustment_lines", "unit_cost")
    op.drop_column("stock_movements", "is_estimated_cost")
    op.drop_column("stock_movements", "value")
    op.drop_column("stock_movements", "unit_cost")
    op.drop_constraint(
        "ck_stock_balances_qty_quality_hold_non_negative",
        "stock_balances",
        type_="check",
    )
    op.drop_column("stock_balances", "qty_quality_hold")
    op.drop_column("products", "requires_qc")
    op.drop_column("tenants", "qc_required_default")
    op.drop_column("tenants", "over_receipt_tolerance_pct")
    op.drop_column("tenants", "allow_over_receipt")
    op.drop_column("tenants", "costing_method")
