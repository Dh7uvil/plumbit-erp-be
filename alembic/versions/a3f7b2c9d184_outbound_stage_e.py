"""Outbound Stage E: delivery notes, packages, shipments, sales returns.

Revision ID: a3f7b2c9d184
Revises: f0c1d5e8a247
Create Date: 2026-09-10 13:50:00.000000
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "a3f7b2c9d184"
down_revision: str | Sequence[str] | None = "f0c1d5e8a247"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
QTY = sa.Numeric(18, 6)
MONEY = sa.Numeric(18, 4)
RATE = sa.Numeric(18, 6)


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
    _add_history_indexes()
    _create_shipment_table()
    _create_delivery_note_tables()
    _create_package_tables()
    _create_sales_return_tables()
    _backfill_sales_return_sequences()
    _backfill_catalog_permissions()


def _add_shared_columns() -> None:
    op.add_column(
        "sales_order_lines",
        sa.Column("qty_returned", QTY, server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "sales_order_lines",
        sa.Column("qty_reserved", QTY, server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "stock_cost_consumptions",
        sa.Column("qty_restored", QTY, server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        "ck_stock_cost_consumptions_qty_restored",
        "stock_cost_consumptions",
        "qty_restored >= 0 AND qty_restored <= qty",
    )


def _add_history_indexes() -> None:
    op.create_index(
        "ix_goods_receipt_lines_tenant_id_product_id",
        "goods_receipt_lines",
        ["tenant_id", "product_id"],
    )
    op.create_index(
        "ix_goods_receipts_tenant_id_supplier_id_document_date",
        "goods_receipts",
        ["tenant_id", "supplier_id", "document_date"],
    )


def _create_shipment_table() -> None:
    op.create_table(
        "shipments",
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
        sa.Column("shipment_type", sa.String(length=30), nullable=False),
        sa.Column("transport_mode", sa.String(length=30), nullable=False),
        sa.Column("incoterm", sa.String(length=10), nullable=True),
        sa.Column("container_number", sa.String(length=80), nullable=True),
        sa.Column("seal_number", sa.String(length=80), nullable=True),
        sa.Column("carrier_name", sa.String(length=120), nullable=True),
        sa.Column("vessel_or_flight_no", sa.String(length=80), nullable=True),
        sa.Column("voyage_number", sa.String(length=80), nullable=True),
        sa.Column("bl_awb_number", sa.String(length=80), nullable=True),
        sa.Column("bl_awb_date", sa.Date(), nullable=True),
        sa.Column("freight_forwarder_id", UUID, nullable=True),
        sa.Column("port_of_loading", sa.String(length=120), nullable=True),
        sa.Column("port_of_discharge", sa.String(length=120), nullable=True),
        sa.Column("etd", sa.Date(), nullable=True),
        sa.Column("eta", sa.Date(), nullable=True),
        sa.Column("actual_departure_date", sa.Date(), nullable=True),
        sa.Column("actual_arrival_date", sa.Date(), nullable=True),
        sa.Column("gross_weight", QTY, nullable=True),
        sa.Column("net_weight", QTY, nullable=True),
        sa.Column("total_packages", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["freight_forwarder_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shipments_tenant_id", "shipments", ["tenant_id"])
    op.create_index("ix_shipments_tenant_id_status", "shipments", ["tenant_id", "status"])
    op.create_index(
        "uq_shipments_tenant_id_document_number_active",
        "shipments",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def _create_delivery_note_tables() -> None:
    op.create_table(
        "delivery_notes",
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
        sa.Column("sales_order_id", UUID, nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("warehouse_id", UUID, nullable=False),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("shipment_id", UUID, nullable=True),
        sa.Column("tax_treatment", sa.String(length=30), nullable=False),
        sa.Column("place_of_supply", sa.String(length=30), nullable=False),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("base_currency_id", UUID, nullable=False),
        sa.Column("exchange_rate", RATE, nullable=False),
        sa.Column("vehicle_number", sa.String(length=80), nullable=True),
        sa.Column("driver_name", sa.String(length=120), nullable=True),
        sa.Column("driver_contact", sa.String(length=40), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", UUID, nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", UUID, nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["base_currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_notes_tenant_id", "delivery_notes", ["tenant_id"])
    op.create_index("ix_delivery_notes_customer_id", "delivery_notes", ["customer_id"])
    op.create_index("ix_delivery_notes_warehouse_id", "delivery_notes", ["warehouse_id"])
    op.create_index("ix_delivery_notes_branch_id", "delivery_notes", ["branch_id"])
    op.create_index("ix_delivery_notes_sales_order_id", "delivery_notes", ["sales_order_id"])
    op.create_index("ix_delivery_notes_shipment_id", "delivery_notes", ["shipment_id"])
    op.create_index("ix_delivery_notes_tenant_id_status", "delivery_notes", ["tenant_id", "status"])
    op.create_index(
        "ix_delivery_notes_tenant_id_document_date",
        "delivery_notes",
        ["tenant_id", "document_date"],
    )
    op.create_index(
        "ix_delivery_notes_tenant_id_customer_id",
        "delivery_notes",
        ["tenant_id", "customer_id"],
    )
    op.create_index(
        "uq_delivery_notes_tenant_id_document_number_active",
        "delivery_notes",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "delivery_note_lines",
        _pk(),
        _tenant(),
        sa.Column("delivery_note_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("sales_order_line_id", UUID, nullable=False),
        sa.Column("product_id", UUID, nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", QTY, nullable=False),
        sa.Column("unit_id", UUID, nullable=True),
        sa.Column("rate", MONEY, server_default=sa.text("0"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["delivery_note_id"], ["delivery_notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["sales_order_line_id"], ["sales_order_lines.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "delivery_note_id",
            "line_number",
            name="uq_delivery_note_lines_header_line_number",
        ),
    )
    op.create_index("ix_delivery_note_lines_tenant_id", "delivery_note_lines", ["tenant_id"])
    op.create_index(
        "ix_delivery_note_lines_delivery_note_id",
        "delivery_note_lines",
        ["delivery_note_id"],
    )
    op.create_index(
        "ix_delivery_note_lines_sales_order_line_id",
        "delivery_note_lines",
        ["sales_order_line_id"],
    )
    op.create_index("ix_delivery_note_lines_product_id", "delivery_note_lines", ["product_id"])
    op.create_index(
        "ix_delivery_note_lines_tenant_id_product_id",
        "delivery_note_lines",
        ["tenant_id", "product_id"],
    )


def _create_package_tables() -> None:
    op.create_table(
        "packages",
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
        sa.Column("sales_order_id", UUID, nullable=False),
        sa.Column("delivery_note_id", UUID, nullable=True),
        sa.Column("package_number", sa.String(length=40), nullable=True),
        sa.Column("length", QTY, nullable=True),
        sa.Column("width", QTY, nullable=True),
        sa.Column("height", QTY, nullable=True),
        sa.Column("dimension_unit", sa.String(length=10), nullable=True),
        sa.Column("gross_weight", QTY, nullable=True),
        sa.Column("net_weight", QTY, nullable=True),
        sa.Column("weight_unit", sa.String(length=10), nullable=True),
        sa.Column("shipping_marks", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["delivery_note_id"], ["delivery_notes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_packages_tenant_id", "packages", ["tenant_id"])
    op.create_index("ix_packages_sales_order_id", "packages", ["sales_order_id"])
    op.create_index("ix_packages_delivery_note_id", "packages", ["delivery_note_id"])
    op.create_index("ix_packages_tenant_id_status", "packages", ["tenant_id", "status"])
    op.create_index(
        "uq_packages_tenant_id_document_number_active",
        "packages",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "package_lines",
        _pk(),
        _tenant(),
        sa.Column("package_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("sales_order_line_id", UUID, nullable=False),
        sa.Column("product_id", UUID, nullable=True),
        sa.Column("quantity", QTY, nullable=False),
        sa.Column("unit_id", UUID, nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["package_id"], ["packages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["sales_order_line_id"], ["sales_order_lines.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "package_id",
            "line_number",
            name="uq_package_lines_header_line_number",
        ),
    )
    op.create_index("ix_package_lines_tenant_id", "package_lines", ["tenant_id"])
    op.create_index("ix_package_lines_package_id", "package_lines", ["package_id"])
    op.create_index(
        "ix_package_lines_sales_order_line_id",
        "package_lines",
        ["sales_order_line_id"],
    )


def _create_sales_return_tables() -> None:
    op.create_table(
        "sales_returns",
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
        sa.Column("delivery_note_id", UUID, nullable=False),
        sa.Column("sales_order_id", UUID, nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("warehouse_id", UUID, nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", UUID, nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", UUID, nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["delivery_note_id"], ["delivery_notes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sales_returns_tenant_id", "sales_returns", ["tenant_id"])
    op.create_index("ix_sales_returns_customer_id", "sales_returns", ["customer_id"])
    op.create_index("ix_sales_returns_warehouse_id", "sales_returns", ["warehouse_id"])
    op.create_index("ix_sales_returns_delivery_note_id", "sales_returns", ["delivery_note_id"])
    op.create_index("ix_sales_returns_sales_order_id", "sales_returns", ["sales_order_id"])
    op.create_index("ix_sales_returns_tenant_id_status", "sales_returns", ["tenant_id", "status"])
    op.create_index(
        "uq_sales_returns_tenant_id_document_number_active",
        "sales_returns",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "sales_return_lines",
        _pk(),
        _tenant(),
        sa.Column("sales_return_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("delivery_note_line_id", UUID, nullable=False),
        sa.Column("product_id", UUID, nullable=True),
        sa.Column("quantity", QTY, nullable=False),
        sa.Column("unit_id", UUID, nullable=True),
        sa.Column("rate", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("disposition", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_return_id"], ["sales_returns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["delivery_note_line_id"], ["delivery_note_lines.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sales_return_id",
            "line_number",
            name="uq_sales_return_lines_header_line_number",
        ),
    )
    op.create_index("ix_sales_return_lines_tenant_id", "sales_return_lines", ["tenant_id"])
    op.create_index(
        "ix_sales_return_lines_sales_return_id",
        "sales_return_lines",
        ["sales_return_id"],
    )
    op.create_index(
        "ix_sales_return_lines_delivery_note_line_id",
        "sales_return_lines",
        ["delivery_note_line_id"],
    )


def _backfill_sales_return_sequences() -> None:
    bind = op.get_bind()
    year = datetime.now(UTC).year
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    for (tenant_id,) in tenants:
        existing = bind.execute(
            sa.text(
                """
                SELECT 1
                FROM document_sequences
                WHERE tenant_id = :tenant_id
                  AND document_type = 'SALES_RETURN'
                  AND series = 'SR'
                  AND fiscal_year = :year
                  AND deleted_at IS NULL
                """
            ),
            {"tenant_id": tenant_id, "year": year},
        ).fetchone()
        if existing is not None:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO document_sequences
                    (tenant_id, document_type, series, fiscal_year, prefix, next_number, padding)
                VALUES (:tenant_id, 'SALES_RETURN', 'SR', :year, 'SR', 1, 6)
                """
            ),
            {"tenant_id": tenant_id, "year": year},
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
    op.drop_table("sales_return_lines")
    op.drop_table("sales_returns")
    op.drop_table("package_lines")
    op.drop_table("packages")
    op.drop_table("delivery_note_lines")
    op.drop_table("delivery_notes")
    op.drop_table("shipments")
    op.drop_index(
        "ix_goods_receipts_tenant_id_supplier_id_document_date",
        table_name="goods_receipts",
    )
    op.drop_index(
        "ix_goods_receipt_lines_tenant_id_product_id",
        table_name="goods_receipt_lines",
    )
    op.drop_constraint(
        "ck_stock_cost_consumptions_qty_restored",
        "stock_cost_consumptions",
        type_="check",
    )
    op.drop_column("stock_cost_consumptions", "qty_restored")
    op.drop_column("sales_order_lines", "qty_reserved")
    op.drop_column("sales_order_lines", "qty_returned")
