"""Cash and bank vouchers.

Revision ID: d4e5f6a7b044
Revises: c3d4e5f6a033
Create Date: 2026-09-22 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "d4e5f6a7b044"
down_revision: str | None = "c3d4e5f6a033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
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
    op.create_table(
        "vouchers",
        _pk(),
        _tenant(),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.Column("document_number", sa.String(length=40), nullable=False),
        sa.Column("voucher_type", sa.String(length=30), nullable=False),
        sa.Column(
            "status", sa.String(length=30), server_default=sa.text("'DRAFT'"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_posted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("voucher_date", sa.Date(), nullable=False),
        sa.Column("payment_account_id", UUID, nullable=False),
        sa.Column("counter_account_id", UUID, nullable=True),
        sa.Column("total_amount", MONEY, nullable=False),
        sa.Column("amount_unapplied", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("base_currency_id", UUID, nullable=False),
        sa.Column("exchange_rate", RATE, nullable=False),
        sa.Column("foreign_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("base_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("party_type", sa.String(length=20), nullable=True),
        sa.Column("party_id", UUID, nullable=True),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("cost_center_id", UUID, nullable=True),
        sa.Column("narration", sa.Text(), nullable=True),
        sa.Column("journal_entry_id", UUID, nullable=True),
        sa.Column("reversal_journal_entry_id", UUID, nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", UUID, nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", UUID, nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["base_currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cost_center_id"], ["cost_centers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["counter_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reversal_journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vouchers_tenant_id_status",
        "vouchers",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_vouchers_tenant_id_voucher_type",
        "vouchers",
        ["tenant_id", "voucher_type"],
        unique=False,
    )
    op.create_index(
        "ix_vouchers_tenant_id_voucher_date",
        "vouchers",
        ["tenant_id", "voucher_date"],
        unique=False,
    )
    op.create_index(
        "uq_vouchers_tenant_id_document_number_active",
        "vouchers",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "voucher_lines",
        _pk(),
        _tenant(),
        *_timestamps(),
        sa.Column("voucher_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("party_type", sa.String(length=20), nullable=True),
        sa.Column("party_id", UUID, nullable=True),
        sa.Column("tax_id", UUID, nullable=True),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("cost_center_id", UUID, nullable=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cost_center_id"], ["cost_centers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tax_id"], ["taxes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["voucher_id"], ["vouchers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("voucher_id", "line_number", name="uq_voucher_lines_header_line"),
    )
    op.create_index("ix_voucher_lines_voucher_id", "voucher_lines", ["voucher_id"], unique=False)
    op.create_index("ix_voucher_lines_account_id", "voucher_lines", ["account_id"], unique=False)

    for document_type, series in (
        ("CASH_RECEIPT_VOUCHER", "CRV"),
        ("CASH_PAYMENT_VOUCHER", "CPV"),
        ("BANK_RECEIPT_VOUCHER", "BRV"),
        ("BANK_PAYMENT_VOUCHER", "BPV"),
        ("CONTRA_VOUCHER", "CON"),
    ):
        op.execute(
            f"""
            INSERT INTO document_sequences (
                id, tenant_id, document_type, series, fiscal_year, prefix, next_number, padding, is_active, created_at, updated_at
            )
            SELECT gen_random_uuid(), t.id, '{document_type}', '{series}', EXTRACT(YEAR FROM CURRENT_DATE)::int, '{series}', 1, 6, true, now(), now()
            FROM tenants t
            WHERE NOT EXISTS (
                SELECT 1 FROM document_sequences ds
                WHERE ds.tenant_id = t.id AND ds.document_type = '{document_type}' AND ds.deleted_at IS NULL
            )
            """
        )

    _backfill_catalog_permissions()


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
    op.drop_index("ix_voucher_lines_account_id", table_name="voucher_lines")
    op.drop_index("ix_voucher_lines_voucher_id", table_name="voucher_lines")
    op.drop_table("voucher_lines")
    op.drop_index("uq_vouchers_tenant_id_document_number_active", table_name="vouchers")
    op.drop_index("ix_vouchers_tenant_id_voucher_date", table_name="vouchers")
    op.drop_index("ix_vouchers_tenant_id_voucher_type", table_name="vouchers")
    op.drop_index("ix_vouchers_tenant_id_status", table_name="vouchers")
    op.drop_table("vouchers")
