"""Chart of accounts, journals, and fiscal year columns.

Revision ID: c1d4e8a6b902
Revises: a3f7b2c9d184
Create Date: 2026-09-10 17:15:00.000000
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "c1d4e8a6b902"
down_revision: str | Sequence[str] | None = "a3f7b2c9d184"
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


def _is_active() -> sa.Column:
    return sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False)


def upgrade() -> None:
    """Apply this revision."""
    op.add_column(
        "tenants",
        sa.Column("fiscal_year_start_month", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "tenants",
        sa.Column("fiscal_year_start_day", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column("tenants", sa.Column("books_start_date", sa.Date(), nullable=True))
    op.create_check_constraint(
        "ck_tenants_fiscal_year_start_month",
        "tenants",
        "fiscal_year_start_month >= 1 AND fiscal_year_start_month <= 12",
    )
    op.create_check_constraint(
        "ck_tenants_fiscal_year_start_day",
        "tenants",
        "fiscal_year_start_day >= 1 AND fiscal_year_start_day <= 31",
    )

    op.create_table(
        "accounts",
        _pk(),
        _tenant(),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("account_subtype", sa.String(length=40), nullable=False),
        sa.Column("parent_id", UUID, nullable=True),
        sa.Column("depth", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_group", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("system_role", sa.String(length=50), nullable=True),
        sa.Column("currency_id", UUID, nullable=True),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        _is_active(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_accounts_tenant_id_code_active",
        "accounts",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_accounts_tenant_id_system_role_active",
        "accounts",
        ["tenant_id", "system_role"],
        unique=True,
        postgresql_where=sa.text("system_role IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index("ix_accounts_tenant_id_parent_id", "accounts", ["tenant_id", "parent_id"])
    op.create_index("ix_accounts_tenant_id_account_type", "accounts", ["tenant_id", "account_type"])
    op.create_index("ix_accounts_parent_id", "accounts", ["parent_id"])
    op.create_index("ix_accounts_currency_id", "accounts", ["currency_id"])
    op.create_index("ix_accounts_tenant_id", "accounts", ["tenant_id"])

    op.add_column("customers", sa.Column("receivable_account_id", UUID, nullable=True))
    op.add_column("customers", sa.Column("payable_account_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_customers_receivable_account_id",
        "customers",
        "accounts",
        ["receivable_account_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_customers_payable_account_id",
        "customers",
        "accounts",
        ["payable_account_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_customers_receivable_account_id", "customers", ["receivable_account_id"])
    op.create_index("ix_customers_payable_account_id", "customers", ["payable_account_id"])

    op.create_table(
        "journal_entries",
        _pk(),
        _tenant(),
        sa.Column("document_number", sa.String(length=40), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_posted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "journal_type", sa.String(length=30), server_default=sa.text("'MANUAL'"), nullable=False
        ),
        sa.Column("source_type", sa.String(length=40), nullable=True),
        sa.Column("source_id", UUID, nullable=True),
        sa.Column("reversal_of_id", UUID, nullable=True),
        sa.Column("reversed_by_id", UUID, nullable=True),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("exchange_rate", RATE, server_default=sa.text("1"), nullable=False),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("narration", sa.Text(), nullable=True),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", UUID, nullable=True),
        sa.Column("total_debit_base", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("total_credit_base", MONEY, server_default=sa.text("0"), nullable=False),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reversal_of_id"], ["journal_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reversed_by_id"], ["journal_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_journal_entries_tenant_id_document_number_active",
        "journal_entries",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_journal_entries_tenant_source_posted",
        "journal_entries",
        ["tenant_id", "source_type", "source_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'POSTED' AND deleted_at IS NULL "
            "AND source_type IS NOT NULL AND source_id IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_journal_entries_tenant_id_entry_date_status",
        "journal_entries",
        ["tenant_id", "entry_date", "status"],
    )
    op.create_index("ix_journal_entries_tenant_id", "journal_entries", ["tenant_id"])
    op.create_index("ix_journal_entries_currency_id", "journal_entries", ["currency_id"])
    op.create_index("ix_journal_entries_branch_id", "journal_entries", ["branch_id"])

    op.create_table(
        "journal_entry_lines",
        _pk(),
        _tenant(),
        sa.Column("journal_entry_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("debit", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("credit", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("debit_base", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("credit_base", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("exchange_rate", RATE, server_default=sa.text("1"), nullable=False),
        sa.Column("party_type", sa.String(length=30), nullable=True),
        sa.Column("party_id", UUID, nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("external_reference", sa.String(length=100), nullable=True),
        sa.Column("tax_id", UUID, nullable=True),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("debit >= 0", name="ck_journal_entry_lines_debit_non_negative"),
        sa.CheckConstraint("credit >= 0", name="ck_journal_entry_lines_credit_non_negative"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["party_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tax_id"], ["taxes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "journal_entry_id", "line_number", name="uq_journal_entry_lines_header_line_number"
        ),
    )
    op.create_index(
        "ix_journal_entry_lines_tenant_account_journal",
        "journal_entry_lines",
        ["tenant_id", "account_id", "journal_entry_id"],
    )
    op.create_index(
        "ix_journal_entry_lines_tenant_party_due",
        "journal_entry_lines",
        ["tenant_id", "party_type", "party_id", "due_date"],
        postgresql_where=sa.text("party_id IS NOT NULL"),
    )
    op.create_index("ix_journal_entry_lines_journal_entry_id", "journal_entry_lines", ["journal_entry_id"])
    op.create_index("ix_journal_entry_lines_account_id", "journal_entry_lines", ["account_id"])
    op.create_index("ix_journal_entry_lines_party_id", "journal_entry_lines", ["party_id"])
    op.create_index("ix_journal_entry_lines_tenant_id", "journal_entry_lines", ["tenant_id"])

    _backfill_journal_sequences()
    _backfill_catalog_permissions()


def _backfill_journal_sequences() -> None:
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
                  AND document_type = 'JOURNAL_ENTRY'
                  AND series = 'JV'
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
                VALUES (:tenant_id, 'JOURNAL_ENTRY', 'JV', :year, 'JV', 1, 6)
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
    op.drop_table("journal_entry_lines")
    op.drop_table("journal_entries")
    op.drop_constraint("fk_customers_payable_account_id", "customers", type_="foreignkey")
    op.drop_constraint("fk_customers_receivable_account_id", "customers", type_="foreignkey")
    op.drop_index("ix_customers_payable_account_id", table_name="customers")
    op.drop_index("ix_customers_receivable_account_id", table_name="customers")
    op.drop_column("customers", "payable_account_id")
    op.drop_column("customers", "receivable_account_id")
    op.drop_table("accounts")
    op.drop_constraint("ck_tenants_fiscal_year_start_day", "tenants", type_="check")
    op.drop_constraint("ck_tenants_fiscal_year_start_month", "tenants", type_="check")
    op.drop_column("tenants", "books_start_date")
    op.drop_column("tenants", "fiscal_year_start_day")
    op.drop_column("tenants", "fiscal_year_start_month")
