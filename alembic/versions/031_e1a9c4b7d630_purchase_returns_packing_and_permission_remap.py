"""Purchase returns, packing columns, debit-note return links, and catalog remap.

Revision ID: e1a9c4b7d630
Revises: d4b8e2a1c507
Create Date: 2026-09-11 18:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions, permission_code_remap

revision: str = "e1a9c4b7d630"
down_revision: str | Sequence[str] | None = "d4b8e2a1c507"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
MONEY = sa.Numeric(18, 4)
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
    _remap_catalog_permissions()
    _add_qty_returned_columns()
    _add_packing_columns()
    _create_purchase_return_tables()
    _alter_debit_notes()
    _backfill_purchase_return_sequences()


def _add_qty_returned_columns() -> None:
    op.add_column(
        "purchase_order_lines",
        sa.Column("qty_returned", QTY, server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "goods_receipt_lines",
        sa.Column("qty_returned", QTY, server_default=sa.text("0"), nullable=False),
    )


def _add_packing_columns() -> None:
    for table in (
        "quotation_lines",
        "proforma_invoice_lines",
        "sales_invoice_lines",
        "package_lines",
    ):
        op.add_column(table, sa.Column("carton_qty", QTY, nullable=True))
        op.add_column(table, sa.Column("packing_unit", sa.String(length=40), nullable=True))
        op.add_column(table, sa.Column("cbm", QTY, nullable=True))
        op.add_column(table, sa.Column("weight", QTY, nullable=True))
        op.add_column(table, sa.Column("item_code", sa.String(length=80), nullable=True))
    op.add_column("quotations", sa.Column("incoterm", sa.String(length=20), nullable=True))
    op.add_column("quotations", sa.Column("incoterm_place", sa.String(length=120), nullable=True))
    op.add_column("sales_invoices", sa.Column("bl_number", sa.String(length=80), nullable=True))
    op.add_column(
        "sales_invoices", sa.Column("container_number", sa.String(length=80), nullable=True)
    )


def _create_purchase_return_tables() -> None:
    op.create_table(
        "purchase_returns",
        _pk(),
        _tenant(),
        sa.Column("document_number", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_posted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("goods_receipt_id", UUID, nullable=False),
        sa.Column("purchase_order_id", UUID, nullable=True),
        sa.Column("supplier_id", UUID, nullable=False),
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
        sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supplier_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_purchase_returns_tenant_id_document_number_active",
        "purchase_returns",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_purchase_returns_tenant_id_status", "purchase_returns", ["tenant_id", "status"])
    op.create_index("ix_purchase_returns_goods_receipt_id", "purchase_returns", ["goods_receipt_id"])
    op.create_index("ix_purchase_returns_purchase_order_id", "purchase_returns", ["purchase_order_id"])
    op.create_index("ix_purchase_returns_supplier_id", "purchase_returns", ["supplier_id"])
    op.create_index("ix_purchase_returns_warehouse_id", "purchase_returns", ["warehouse_id"])

    op.create_table(
        "purchase_return_lines",
        _pk(),
        _tenant(),
        sa.Column("purchase_return_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("goods_receipt_line_id", UUID, nullable=False),
        sa.Column("product_id", UUID, nullable=True),
        sa.Column("quantity", QTY, nullable=False),
        sa.Column("unit_id", UUID, nullable=True),
        sa.Column("rate", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("disposition", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["purchase_return_id"], ["purchase_returns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["goods_receipt_line_id"], ["goods_receipt_lines.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "purchase_return_id",
            "line_number",
            name="uq_purchase_return_lines_header_line_number",
        ),
    )
    op.create_index(
        "ix_purchase_return_lines_purchase_return_id",
        "purchase_return_lines",
        ["purchase_return_id"],
    )
    op.create_index(
        "ix_purchase_return_lines_goods_receipt_line_id",
        "purchase_return_lines",
        ["goods_receipt_line_id"],
    )


def _alter_debit_notes() -> None:
    op.alter_column("debit_notes", "purchase_invoice_id", existing_type=UUID, nullable=True)
    op.add_column("debit_notes", sa.Column("purchase_return_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_debit_notes_purchase_return_id",
        "debit_notes",
        "purchase_returns",
        ["purchase_return_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_debit_notes_tenant_id_purchase_return_id",
        "debit_notes",
        ["tenant_id", "purchase_return_id"],
    )
    op.alter_column(
        "debit_note_lines", "purchase_invoice_line_id", existing_type=UUID, nullable=True
    )
    op.add_column("debit_note_lines", sa.Column("purchase_return_line_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_debit_note_lines_purchase_return_line_id",
        "debit_note_lines",
        "purchase_return_lines",
        ["purchase_return_line_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_debit_note_lines_purchase_return_line_id",
        "debit_note_lines",
        ["purchase_return_line_id"],
    )


def _split_code(code: str) -> tuple[str, str, str]:
    module, resource, action = code.split(".", 2)
    return module, resource, action


def _remap_catalog_permissions() -> None:
    bind = op.get_bind()
    catalog = parsed_catalog_permissions()
    remap = permission_code_remap()
    remap["erp.report.vat"] = "reports.report.tax"

    for parsed in catalog:
        bind.execute(
            sa.text(
                """
                INSERT INTO permissions (tenant_id, module, resource, action)
                SELECT t.id,
                       CAST(:module AS VARCHAR),
                       CAST(:resource AS VARCHAR),
                       CAST(:action AS VARCHAR)
                FROM tenants t
                WHERE NOT EXISTS (
                    SELECT 1 FROM permissions p
                    WHERE p.tenant_id = t.id
                      AND p.module = CAST(:module AS VARCHAR)
                      AND p.resource = CAST(:resource AS VARCHAR)
                      AND p.action = CAST(:action AS VARCHAR)
                )
                """
            ),
            {
                "module": parsed.module,
                "resource": parsed.resource,
                "action": parsed.action,
            },
        )

    for old_code, new_code in remap.items():
        if old_code == new_code:
            continue
        old_module, old_resource, old_action = _split_code(old_code)
        new_module, new_resource, new_action = _split_code(new_code)
        bind.execute(
            sa.text(
                """
                INSERT INTO role_permissions (tenant_id, role_id, permission_id)
                SELECT rp.tenant_id, rp.role_id, new_p.id
                FROM role_permissions rp
                JOIN permissions old_p
                  ON old_p.id = rp.permission_id
                 AND old_p.tenant_id = rp.tenant_id
                JOIN permissions new_p
                  ON new_p.tenant_id = rp.tenant_id
                 AND new_p.module = CAST(:new_module AS VARCHAR)
                 AND new_p.resource = CAST(:new_resource AS VARCHAR)
                 AND new_p.action = CAST(:new_action AS VARCHAR)
                WHERE old_p.module = CAST(:old_module AS VARCHAR)
                  AND old_p.resource = CAST(:old_resource AS VARCHAR)
                  AND old_p.action = CAST(:old_action AS VARCHAR)
                  AND old_p.id <> new_p.id
                  AND NOT EXISTS (
                      SELECT 1 FROM role_permissions existing
                      WHERE existing.tenant_id = rp.tenant_id
                        AND existing.role_id = rp.role_id
                        AND existing.permission_id = new_p.id
                  )
                """
            ),
            {
                "old_module": old_module,
                "old_resource": old_resource,
                "old_action": old_action,
                "new_module": new_module,
                "new_resource": new_resource,
                "new_action": new_action,
            },
        )
        bind.execute(
            sa.text(
                """
                DELETE FROM role_permissions rp
                USING permissions p
                WHERE rp.permission_id = p.id
                  AND p.module = CAST(:module AS VARCHAR)
                  AND p.resource = CAST(:resource AS VARCHAR)
                  AND p.action = CAST(:action AS VARCHAR)
                """
            ),
            {"module": old_module, "resource": old_resource, "action": old_action},
        )
        bind.execute(
            sa.text(
                """
                DELETE FROM permissions
                WHERE module = CAST(:module AS VARCHAR)
                  AND resource = CAST(:resource AS VARCHAR)
                  AND action = CAST(:action AS VARCHAR)
                """
            ),
            {"module": old_module, "resource": old_resource, "action": old_action},
        )

    bind.execute(
        sa.text(
            """
            INSERT INTO role_permissions (tenant_id, role_id, permission_id)
            SELECT r.tenant_id, r.id, p.id
            FROM roles r
            JOIN permissions p ON p.tenant_id = r.tenant_id
            WHERE r.is_system_role = true
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp
                  WHERE rp.tenant_id = r.tenant_id
                    AND rp.role_id = r.id
                    AND rp.permission_id = p.id
              )
            """
        )
    )


def _backfill_purchase_return_sequences() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT DISTINCT tenant_id, fiscal_year
            FROM document_sequences
            WHERE deleted_at IS NULL
            """
        )
    ).fetchall()
    for tenant_id, fiscal_year in rows:
        existing = bind.execute(
            sa.text(
                """
                SELECT id FROM document_sequences
                WHERE tenant_id = :tenant_id
                  AND document_type = 'PURCHASE_RETURN'
                  AND series = 'PR'
                  AND fiscal_year = :fiscal_year
                  AND deleted_at IS NULL
                """
            ),
            {"tenant_id": tenant_id, "fiscal_year": fiscal_year},
        ).fetchone()
        if existing is not None:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO document_sequences (
                    tenant_id, document_type, series, fiscal_year, prefix,
                    next_number, padding, is_active
                )
                VALUES (
                    :tenant_id, 'PURCHASE_RETURN', 'PR', :fiscal_year, 'PR', 1, 6, true
                )
                """
            ),
            {"tenant_id": tenant_id, "fiscal_year": fiscal_year},
        )


def downgrade() -> None:
    """Revert this revision."""
    op.drop_index("ix_debit_note_lines_purchase_return_line_id", table_name="debit_note_lines")
    op.drop_constraint(
        "fk_debit_note_lines_purchase_return_line_id", "debit_note_lines", type_="foreignkey"
    )
    op.drop_column("debit_note_lines", "purchase_return_line_id")
    op.alter_column(
        "debit_note_lines", "purchase_invoice_line_id", existing_type=UUID, nullable=False
    )
    op.drop_index("ix_debit_notes_tenant_id_purchase_return_id", table_name="debit_notes")
    op.drop_constraint("fk_debit_notes_purchase_return_id", "debit_notes", type_="foreignkey")
    op.drop_column("debit_notes", "purchase_return_id")
    op.alter_column("debit_notes", "purchase_invoice_id", existing_type=UUID, nullable=False)
    op.drop_table("purchase_return_lines")
    op.drop_table("purchase_returns")
    op.drop_column("sales_invoices", "container_number")
    op.drop_column("sales_invoices", "bl_number")
    op.drop_column("quotations", "incoterm_place")
    op.drop_column("quotations", "incoterm")
    for table in (
        "package_lines",
        "sales_invoice_lines",
        "proforma_invoice_lines",
        "quotation_lines",
    ):
        op.drop_column(table, "item_code")
        op.drop_column(table, "weight")
        op.drop_column(table, "cbm")
        op.drop_column(table, "packing_unit")
        op.drop_column(table, "carton_qty")
    op.drop_column("goods_receipt_lines", "qty_returned")
    op.drop_column("purchase_order_lines", "qty_returned")
