"""stock inventory balances, movements, transfers, and adjustments

Revision ID: d1e5f8a2c904
Revises: b7c1e4a9d205
Create Date: 2026-09-02 16:30:00.000000
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "d1e5f8a2c904"
down_revision: str | Sequence[str] | None = "b7c1e4a9d205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
QTY = sa.Numeric(18, 6)


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
    op.add_column(
        "tenants",
        sa.Column(
            "allow_negative_stock",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column("tenants", sa.Column("lock_date", sa.Date(), nullable=True))
    op.add_column("tenants", sa.Column("hard_lock_date", sa.Date(), nullable=True))

    op.create_table(
        "idempotency_keys",
        _pk(),
        _tenant(),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("endpoint", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_idempotency_keys_tenant_id_key"),
    )
    op.create_index("ix_idempotency_keys_tenant_id", "idempotency_keys", ["tenant_id"])

    op.create_table(
        "stock_balances",
        _pk(),
        _tenant(),
        sa.Column("warehouse_id", UUID, nullable=False),
        sa.Column("product_id", UUID, nullable=False),
        sa.Column("qty_on_hand", QTY, server_default=sa.text("0"), nullable=False),
        sa.Column("qty_reserved", QTY, server_default=sa.text("0"), nullable=False),
        sa.Column("qty_incoming", QTY, server_default=sa.text("0"), nullable=False),
        sa.Column("qty_outgoing", QTY, server_default=sa.text("0"), nullable=False),
        sa.Column("qty_in_transit", QTY, server_default=sa.text("0"), nullable=False),
        sa.Column("reorder_level", QTY, nullable=True),
        sa.Column("reorder_qty", QTY, nullable=True),
        sa.Column("last_movement_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "warehouse_id",
            "product_id",
            name="uq_stock_balances_tenant_warehouse_product",
        ),
        sa.CheckConstraint("qty_reserved >= 0", name="ck_stock_balances_qty_reserved_non_negative"),
        sa.CheckConstraint("qty_incoming >= 0", name="ck_stock_balances_qty_incoming_non_negative"),
        sa.CheckConstraint("qty_outgoing >= 0", name="ck_stock_balances_qty_outgoing_non_negative"),
        sa.CheckConstraint(
            "qty_in_transit >= 0", name="ck_stock_balances_qty_in_transit_non_negative"
        ),
    )
    op.create_index("ix_stock_balances_tenant_id", "stock_balances", ["tenant_id"])
    op.create_index("ix_stock_balances_warehouse_id", "stock_balances", ["warehouse_id"])
    op.create_index("ix_stock_balances_product_id", "stock_balances", ["product_id"])
    op.create_index(
        "ix_stock_balances_tenant_id_product_id", "stock_balances", ["tenant_id", "product_id"]
    )
    op.create_index(
        "ix_stock_balances_tenant_id_warehouse_id",
        "stock_balances",
        ["tenant_id", "warehouse_id"],
    )

    op.create_table(
        "stock_movements",
        _pk(),
        _tenant(),
        sa.Column("movement_type", sa.String(length=30), nullable=False),
        sa.Column("warehouse_id", UUID, nullable=False),
        sa.Column("product_id", UUID, nullable=False),
        sa.Column("unit_id", UUID, nullable=True),
        sa.Column("qty", QTY, nullable=False),
        sa.Column("qty_before", QTY, nullable=False),
        sa.Column("qty_after", QTY, nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", UUID, nullable=False),
        sa.Column("source_line_id", UUID, nullable=True),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_movements_tenant_id", "stock_movements", ["tenant_id"])
    op.create_index("ix_stock_movements_warehouse_id", "stock_movements", ["warehouse_id"])
    op.create_index("ix_stock_movements_product_id", "stock_movements", ["product_id"])
    op.create_index(
        "ix_stock_movements_tenant_product_warehouse_date",
        "stock_movements",
        ["tenant_id", "product_id", "warehouse_id", "document_date"],
    )
    op.create_index(
        "ix_stock_movements_tenant_source",
        "stock_movements",
        ["tenant_id", "source_type", "source_id"],
    )

    _create_adjustment_tables()
    _create_transfer_tables()
    _backfill_catalog_and_sequences()


def _create_adjustment_tables() -> None:
    op.create_table(
        "stock_adjustments",
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
        sa.Column("warehouse_id", UUID, nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("reference", sa.String(length=100), nullable=True),
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
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_adjustments_tenant_id", "stock_adjustments", ["tenant_id"])
    op.create_index("ix_stock_adjustments_warehouse_id", "stock_adjustments", ["warehouse_id"])
    op.create_index("ix_stock_adjustments_branch_id", "stock_adjustments", ["branch_id"])
    op.create_index(
        "ix_stock_adjustments_tenant_id_status", "stock_adjustments", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_stock_adjustments_tenant_id_document_date",
        "stock_adjustments",
        ["tenant_id", "document_date"],
    )
    op.create_index(
        "uq_stock_adjustments_tenant_id_document_number_active",
        "stock_adjustments",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "stock_adjustment_lines",
        _pk(),
        _tenant(),
        sa.Column("stock_adjustment_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("product_id", UUID, nullable=False),
        sa.Column("unit_id", UUID, nullable=True),
        sa.Column("qty_counted", QTY, nullable=True),
        sa.Column("qty_booked", QTY, nullable=True),
        sa.Column("qty_delta", QTY, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["stock_adjustment_id"], ["stock_adjustments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_adjustment_id",
            "line_number",
            name="uq_stock_adjustment_lines_header_line_number",
        ),
        sa.UniqueConstraint(
            "stock_adjustment_id",
            "product_id",
            name="uq_stock_adjustment_lines_header_product",
        ),
    )
    op.create_index("ix_stock_adjustment_lines_tenant_id", "stock_adjustment_lines", ["tenant_id"])
    op.create_index(
        "ix_stock_adjustment_lines_stock_adjustment_id",
        "stock_adjustment_lines",
        ["stock_adjustment_id"],
    )
    op.create_index(
        "ix_stock_adjustment_lines_product_id", "stock_adjustment_lines", ["product_id"]
    )


def _create_transfer_tables() -> None:
    op.create_table(
        "stock_transfers",
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
        sa.Column("from_warehouse_id", UUID, nullable=False),
        sa.Column("to_warehouse_id", UUID, nullable=False),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("reference", sa.String(length=100), nullable=True),
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
        sa.ForeignKeyConstraint(["from_warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_transfers_tenant_id", "stock_transfers", ["tenant_id"])
    op.create_index(
        "ix_stock_transfers_from_warehouse_id", "stock_transfers", ["from_warehouse_id"]
    )
    op.create_index("ix_stock_transfers_to_warehouse_id", "stock_transfers", ["to_warehouse_id"])
    op.create_index("ix_stock_transfers_branch_id", "stock_transfers", ["branch_id"])
    op.create_index(
        "ix_stock_transfers_tenant_id_status", "stock_transfers", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_stock_transfers_tenant_id_document_date",
        "stock_transfers",
        ["tenant_id", "document_date"],
    )
    op.create_index(
        "uq_stock_transfers_tenant_id_document_number_active",
        "stock_transfers",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "stock_transfer_lines",
        _pk(),
        _tenant(),
        sa.Column("stock_transfer_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("product_id", UUID, nullable=False),
        sa.Column("unit_id", UUID, nullable=True),
        sa.Column("qty", QTY, nullable=False),
        sa.Column("qty_transferred", QTY, server_default=sa.text("0"), nullable=False),
        sa.Column("qty_source_before", QTY, nullable=True),
        sa.Column("qty_dest_before", QTY, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stock_transfer_id"], ["stock_transfers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_transfer_id",
            "line_number",
            name="uq_stock_transfer_lines_header_line_number",
        ),
        sa.UniqueConstraint(
            "stock_transfer_id",
            "product_id",
            name="uq_stock_transfer_lines_header_product",
        ),
    )
    op.create_index("ix_stock_transfer_lines_tenant_id", "stock_transfer_lines", ["tenant_id"])
    op.create_index(
        "ix_stock_transfer_lines_stock_transfer_id",
        "stock_transfer_lines",
        ["stock_transfer_id"],
    )
    op.create_index("ix_stock_transfer_lines_product_id", "stock_transfer_lines", ["product_id"])


def _backfill_catalog_and_sequences() -> None:
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    catalog = parsed_catalog_permissions()
    fiscal_year = datetime.now(UTC).year
    sequences = (("STOCK_TRANSFER", "STR"), ("STOCK_ADJUSTMENT", "STA"))

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

        for document_type, series in sequences:
            already = bind.execute(
                sa.text(
                    """
                    SELECT id FROM document_sequences
                    WHERE tenant_id = :tenant_id
                      AND document_type = :document_type
                      AND series = :series
                      AND fiscal_year = :fiscal_year
                      AND deleted_at IS NULL
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "document_type": document_type,
                    "series": series,
                    "fiscal_year": fiscal_year,
                },
            ).fetchone()
            if already is not None:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO document_sequences (
                        tenant_id, document_type, series, fiscal_year, prefix, next_number, padding
                    )
                    VALUES (
                        :tenant_id, :document_type, :series, :fiscal_year, :prefix, 1, 6
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "document_type": document_type,
                    "series": series,
                    "fiscal_year": fiscal_year,
                    "prefix": series,
                },
            )


def downgrade() -> None:
    """Revert this revision."""
    op.drop_table("stock_transfer_lines")
    op.drop_table("stock_transfers")
    op.drop_table("stock_adjustment_lines")
    op.drop_table("stock_adjustments")
    op.drop_table("stock_movements")
    op.drop_table("stock_balances")
    op.drop_table("idempotency_keys")
    op.drop_column("tenants", "hard_lock_date")
    op.drop_column("tenants", "lock_date")
    op.drop_column("tenants", "allow_negative_stock")
