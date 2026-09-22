"""Bank accounts, reconciliation, cheques and PDC clearing accounts.

Revision ID: f6a7b8c9d066
Revises: e5f6a7b8c055
Create Date: 2026-09-22 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "f6a7b8c9d066"
down_revision: str | None = "e5f6a7b8c055"
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
        "bank_accounts",
        _pk(),
        _tenant(),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("account_name", sa.String(length=150), nullable=False),
        sa.Column("bank_name", sa.String(length=150), nullable=False),
        sa.Column("branch_name", sa.String(length=150), nullable=True),
        sa.Column("account_number", sa.String(length=50), nullable=True),
        sa.Column("iban", sa.String(length=50), nullable=True),
        sa.Column("swift", sa.String(length=20), nullable=True),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("opening_balance", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("opening_date", sa.Date(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_bank_accounts_tenant_id_account_id_active",
        "bank_accounts",
        ["tenant_id", "account_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_bank_accounts_tenant_id_is_active",
        "bank_accounts",
        ["tenant_id", "is_active"],
        unique=False,
    )

    op.create_table(
        "bank_statements",
        _pk(),
        _tenant(),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.Column("bank_account_id", UUID, nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("opening_balance", MONEY, nullable=False),
        sa.Column("closing_balance", MONEY, nullable=False),
        sa.Column(
            "status", sa.String(length=30), server_default=sa.text("'DRAFT'"), nullable=False
        ),
        sa.Column("import_reference", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bank_statements_tenant_id_bank_account_id",
        "bank_statements",
        ["tenant_id", "bank_account_id"],
        unique=False,
    )
    op.create_index(
        "ix_bank_statements_tenant_id_status",
        "bank_statements",
        ["tenant_id", "status"],
        unique=False,
    )

    op.create_table(
        "bank_statement_lines",
        _pk(),
        _tenant(),
        *_timestamps(),
        sa.Column("bank_statement_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("line_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("debit", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("credit", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column(
            "match_status",
            sa.String(length=30),
            server_default=sa.text("'UNMATCHED'"),
            nullable=False,
        ),
        sa.Column("matched_journal_line_id", UUID, nullable=True),
        sa.ForeignKeyConstraint(["bank_statement_id"], ["bank_statements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["matched_journal_line_id"], ["journal_entry_lines.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bank_statement_id", "line_number", name="uq_bank_statement_lines_line"
        ),
    )
    op.create_index(
        "ix_bank_statement_lines_statement_id",
        "bank_statement_lines",
        ["bank_statement_id"],
        unique=False,
    )
    op.create_index(
        "ix_bank_statement_lines_match_status",
        "bank_statement_lines",
        ["tenant_id", "match_status"],
        unique=False,
    )

    op.create_table(
        "cheques",
        _pk(),
        _tenant(),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.Column("document_number", sa.String(length=40), nullable=False),
        sa.Column("cheque_number", sa.String(length=50), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column(
            "status", sa.String(length=30), server_default=sa.text("'DRAFT'"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_posted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("cheque_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("amount_unapplied", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("base_currency_id", UUID, nullable=False),
        sa.Column("exchange_rate", RATE, nullable=False),
        sa.Column("foreign_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("base_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("party_type", sa.String(length=20), nullable=True),
        sa.Column("party_id", UUID, nullable=True),
        sa.Column("bank_account_id", UUID, nullable=False),
        sa.Column("customer_payment_id", UUID, nullable=True),
        sa.Column("supplier_payment_id", UUID, nullable=True),
        sa.Column("voucher_id", UUID, nullable=True),
        sa.Column("narration", sa.Text(), nullable=True),
        sa.Column("journal_entry_id", UUID, nullable=True),
        sa.Column("clearing_journal_entry_id", UUID, nullable=True),
        sa.Column("reversal_journal_entry_id", UUID, nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_by", UUID, nullable=True),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleared_by", UUID, nullable=True),
        sa.Column("bounced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bounced_by", UUID, nullable=True),
        sa.Column("bounce_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["base_currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cleared_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["customer_payment_id"], ["customer_payments.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["issued_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["clearing_journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reversal_journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["supplier_payment_id"], ["supplier_payments.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["voucher_id"], ["vouchers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["bounced_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_cheques_tenant_id_document_number_active",
        "cheques",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_cheques_tenant_id_status", "cheques", ["tenant_id", "status"], unique=False)
    op.create_index(
        "ix_cheques_tenant_id_due_date", "cheques", ["tenant_id", "due_date"], unique=False
    )
    op.create_index(
        "ix_cheques_tenant_id_cheque_number",
        "cheques",
        ["tenant_id", "cheque_number"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO document_sequences (
            id, tenant_id, document_type, series, fiscal_year, prefix,
            next_number, padding, is_active, created_at, updated_at
        )
        SELECT gen_random_uuid(), t.id, 'CHEQUE', 'CHQ',
            EXTRACT(YEAR FROM CURRENT_DATE)::int, 'CHQ', 1, 6, true, now(), now()
        FROM tenants t
        WHERE NOT EXISTS (
            SELECT 1 FROM document_sequences ds
            WHERE ds.tenant_id = t.id AND ds.document_type = 'CHEQUE' AND ds.deleted_at IS NULL
        )
        """
    )

    _backfill_cheque_accounts()
    _backfill_catalog_permissions()


def _backfill_cheque_accounts() -> None:
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    for (tenant_id,) in tenants:
        parent_asset = bind.execute(
            sa.text(
                """
                SELECT id, depth FROM accounts
                WHERE tenant_id = :tenant_id AND code = '1000' AND deleted_at IS NULL
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        parent_liability = bind.execute(
            sa.text(
                """
                SELECT id, depth FROM accounts
                WHERE tenant_id = :tenant_id AND code = '2000' AND deleted_at IS NULL
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if parent_asset is not None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO accounts (
                        tenant_id, code, name, account_type, account_subtype, parent_id,
                        depth, is_group, is_system, system_role, is_active
                    )
                    SELECT :tenant_id, '1120', 'Cheques Receivable', 'ASSET',
                           'OTHER_CURRENT_ASSET', :parent_id, :depth, false, true,
                           'CHEQUES_RECEIVABLE', true
                    WHERE NOT EXISTS (
                        SELECT 1 FROM accounts
                        WHERE tenant_id = :tenant_id
                          AND system_role = 'CHEQUES_RECEIVABLE'
                          AND deleted_at IS NULL
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "parent_id": parent_asset.id,
                    "depth": parent_asset.depth + 1,
                },
            )
        if parent_liability is not None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO accounts (
                        tenant_id, code, name, account_type, account_subtype, parent_id,
                        depth, is_group, is_system, system_role, is_active
                    )
                    SELECT :tenant_id, '2025', 'Cheques Payable', 'LIABILITY',
                           'OTHER_CURRENT_LIABILITY', :parent_id, :depth, false, true,
                           'CHEQUES_PAYABLE', true
                    WHERE NOT EXISTS (
                        SELECT 1 FROM accounts
                        WHERE tenant_id = :tenant_id
                          AND system_role = 'CHEQUES_PAYABLE'
                          AND deleted_at IS NULL
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "parent_id": parent_liability.id,
                    "depth": parent_liability.depth + 1,
                },
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
                WHERE tenant_id = :tenant_id AND is_system_role = true
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
                        SELECT 1 FROM role_permissions rp
                        WHERE rp.tenant_id = :tenant_id
                          AND rp.role_id = :role_id
                          AND rp.permission_id = p.id
                      )
                    """
                ),
                {"tenant_id": tenant_id, "role_id": admin.id},
            )


def downgrade() -> None:
    op.drop_index("ix_cheques_tenant_id_cheque_number", table_name="cheques")
    op.drop_index("ix_cheques_tenant_id_due_date", table_name="cheques")
    op.drop_index("ix_cheques_tenant_id_status", table_name="cheques")
    op.drop_index("uq_cheques_tenant_id_document_number_active", table_name="cheques")
    op.drop_table("cheques")
    op.drop_index("ix_bank_statement_lines_match_status", table_name="bank_statement_lines")
    op.drop_index("ix_bank_statement_lines_statement_id", table_name="bank_statement_lines")
    op.drop_table("bank_statement_lines")
    op.drop_index("ix_bank_statements_tenant_id_status", table_name="bank_statements")
    op.drop_index("ix_bank_statements_tenant_id_bank_account_id", table_name="bank_statements")
    op.drop_table("bank_statements")
    op.drop_index("ix_bank_accounts_tenant_id_is_active", table_name="bank_accounts")
    op.drop_index("uq_bank_accounts_tenant_id_account_id_active", table_name="bank_accounts")
    op.drop_table("bank_accounts")
