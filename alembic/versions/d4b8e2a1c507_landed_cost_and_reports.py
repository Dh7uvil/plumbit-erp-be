"""Landed cost tables, warehouse designated zone, and catalog backfill.

Revision ID: d4b8e2a1c507
Revises: c8f1a4d6e209
Create Date: 2026-09-11 16:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "d4b8e2a1c507"
down_revision: str | Sequence[str] | None = "c8f1a4d6e209"
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
    op.add_column(
        "warehouses",
        sa.Column(
            "is_designated_zone",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    _create_landed_cost_tables()
    _backfill_catalog_permissions()
    _backfill_landed_cost_variance_accounts()
    _backfill_landed_cost_sequences()


def _create_landed_cost_tables() -> None:
    op.create_table(
        "landed_costs",
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
        sa.Column(
            "allocation_method",
            sa.String(length=20),
            server_default=sa.text("'VALUE'"),
            nullable=False,
        ),
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
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reversal_journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_landed_costs_tenant_id", "landed_costs", ["tenant_id"])
    op.create_index("ix_landed_costs_shipment_id", "landed_costs", ["shipment_id"])
    op.create_index("ix_landed_costs_branch_id", "landed_costs", ["branch_id"])
    op.create_index("ix_landed_costs_tenant_id_status", "landed_costs", ["tenant_id", "status"])
    op.create_index(
        "ix_landed_costs_tenant_id_document_date",
        "landed_costs",
        ["tenant_id", "document_date"],
    )
    op.create_index(
        "ix_landed_costs_tenant_id_shipment_id",
        "landed_costs",
        ["tenant_id", "shipment_id"],
    )
    op.create_index(
        "uq_landed_costs_tenant_id_document_number_active",
        "landed_costs",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "landed_cost_charges",
        _pk(),
        _tenant(),
        sa.Column("landed_cost_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("purchase_invoice_id", UUID, nullable=False),
        sa.Column("purchase_invoice_line_id", UUID, nullable=False),
        sa.Column("expense_category", sa.String(length=30), nullable=False),
        sa.Column("bill_number", sa.String(length=40), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["landed_cost_id"], ["landed_costs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["purchase_invoice_id"], ["purchase_invoices.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["purchase_invoice_line_id"],
            ["purchase_invoice_lines.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "landed_cost_id",
            "line_number",
            name="uq_landed_cost_charges_header_line_number",
        ),
        sa.UniqueConstraint(
            "landed_cost_id",
            "purchase_invoice_line_id",
            name="uq_landed_cost_charges_header_bill_line",
        ),
    )
    op.create_index("ix_landed_cost_charges_tenant_id", "landed_cost_charges", ["tenant_id"])
    op.create_index(
        "ix_landed_cost_charges_landed_cost_id", "landed_cost_charges", ["landed_cost_id"]
    )
    op.create_index(
        "ix_landed_cost_charges_purchase_invoice_id",
        "landed_cost_charges",
        ["purchase_invoice_id"],
    )
    op.create_index(
        "ix_landed_cost_charges_purchase_invoice_line_id",
        "landed_cost_charges",
        ["purchase_invoice_line_id"],
    )

    op.create_table(
        "landed_cost_allocations",
        _pk(),
        _tenant(),
        sa.Column("landed_cost_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("goods_receipt_id", UUID, nullable=False),
        sa.Column("goods_receipt_line_id", UUID, nullable=False),
        sa.Column("allocation_base", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("allocated_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("qty_remaining_at_post", QTY, nullable=True),
        sa.Column("qty_consumed_at_post", QTY, nullable=True),
        sa.Column("previous_landed_unit_cost", MONEY, nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["landed_cost_id"], ["landed_costs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["goods_receipt_line_id"], ["goods_receipt_lines.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "landed_cost_id",
            "line_number",
            name="uq_landed_cost_allocations_header_line_number",
        ),
        sa.UniqueConstraint(
            "landed_cost_id",
            "goods_receipt_line_id",
            name="uq_landed_cost_allocations_header_grn_line",
        ),
    )
    op.create_index(
        "ix_landed_cost_allocations_tenant_id", "landed_cost_allocations", ["tenant_id"]
    )
    op.create_index(
        "ix_landed_cost_allocations_landed_cost_id",
        "landed_cost_allocations",
        ["landed_cost_id"],
    )
    op.create_index(
        "ix_landed_cost_allocations_goods_receipt_id",
        "landed_cost_allocations",
        ["goods_receipt_id"],
    )
    op.create_index(
        "ix_landed_cost_allocations_goods_receipt_line_id",
        "landed_cost_allocations",
        ["goods_receipt_line_id"],
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


def _backfill_landed_cost_variance_accounts() -> None:
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    for (tenant_id,) in tenants:
        parent = bind.execute(
            sa.text(
                """
                SELECT id, depth FROM accounts
                WHERE tenant_id = :tenant_id
                  AND code = '5000'
                  AND deleted_at IS NULL
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if parent is None:
            continue
        existing = bind.execute(
            sa.text(
                """
                SELECT id, system_role FROM accounts
                WHERE tenant_id = :tenant_id
                  AND code = '5250'
                  AND deleted_at IS NULL
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        mapped = bind.execute(
            sa.text(
                """
                SELECT id FROM accounts
                WHERE tenant_id = :tenant_id
                  AND system_role = 'LANDED_COST_VARIANCE'
                  AND deleted_at IS NULL
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if existing is None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO accounts (
                        tenant_id, code, name, account_type, account_subtype,
                        parent_id, depth, is_group, is_system, system_role, is_active
                    )
                    VALUES (
                        :tenant_id, '5250', 'Landed Cost Variance', 'EXPENSE', 'COGS',
                        :parent_id, :depth, false, true, :system_role, true
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "parent_id": parent.id,
                    "depth": parent.depth + 1,
                    "system_role": None if mapped is not None else "LANDED_COST_VARIANCE",
                },
            )
            continue
        if mapped is None and existing.system_role is None:
            bind.execute(
                sa.text(
                    """
                    UPDATE accounts
                    SET system_role = 'LANDED_COST_VARIANCE', is_system = true
                    WHERE id = :account_id
                    """
                ),
                {"account_id": existing.id},
            )


def _backfill_landed_cost_sequences() -> None:
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
                  AND document_type = 'LANDED_COST'
                  AND series = 'LC'
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
                    :tenant_id, 'LANDED_COST', 'LC', :fiscal_year, 'LC', 1, 6, true
                )
                """
            ),
            {"tenant_id": tenant_id, "fiscal_year": fiscal_year},
        )


def downgrade() -> None:
    """Revert this revision."""
    op.drop_table("landed_cost_allocations")
    op.drop_table("landed_cost_charges")
    op.drop_table("landed_costs")
    op.drop_column("warehouses", "is_designated_zone")
