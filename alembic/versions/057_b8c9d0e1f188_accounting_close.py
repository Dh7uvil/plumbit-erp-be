"""Budgets, recurring templates, FX revaluation, and report export jobs.

Revision ID: b8c9d0e1f188
Revises: a7b8c9d0e177
Create Date: 2026-09-23 09:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "b8c9d0e1f188"
down_revision: str | None = "a7b8c9d0e177"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
MONEY = sa.Numeric(18, 4)
RATE = sa.Numeric(18, 6)
JSONB = postgresql.JSONB(astext_type=sa.Text())


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
        "budgets",
        _pk(),
        _tenant(),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_budgets_tenant_id_status", "budgets", ["tenant_id", "status"])
    op.create_index("ix_budgets_tenant_id_fiscal_year", "budgets", ["tenant_id", "fiscal_year"])

    op.create_table(
        "budget_lines",
        _pk(),
        _tenant(),
        *_timestamps(),
        sa.Column("budget_id", UUID, nullable=False),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("cost_center_id", UUID, nullable=True),
        sa.Column("branch_id", UUID, nullable=True),
        sa.ForeignKeyConstraint(["budget_id"], ["budgets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cost_center_id"], ["cost_centers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_budget_lines_tenant_id_budget_id",
        "budget_lines",
        ["tenant_id", "budget_id"],
    )

    op.create_table(
        "recurring_templates",
        _pk(),
        _tenant(),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("document_kind", sa.String(length=30), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False),
        sa.Column("interval", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("next_run_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("max_occurrences", sa.Integer(), nullable=True),
        sa.Column(
            "occurrences_generated", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("template_payload", JSONB, nullable=False),
        sa.Column("last_document_id", UUID, nullable=True),
        sa.Column("last_document_number", sa.String(length=50), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recurring_templates_tenant_id_status", "recurring_templates", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_recurring_templates_tenant_id_next_run",
        "recurring_templates",
        ["tenant_id", "next_run_date"],
    )

    op.create_table(
        "recurring_generations",
        _pk(),
        _tenant(),
        *_timestamps(),
        sa.Column("template_id", UUID, nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("document_kind", sa.String(length=30), nullable=False),
        sa.Column("document_id", UUID, nullable=True),
        sa.Column("document_number", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["recurring_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "template_id", "run_date", name="uq_recurring_generations_template_run"
        ),
    )

    op.create_table(
        "fx_revaluation_runs",
        _pk(),
        _tenant(),
        *_timestamps(),
        _soft_delete(),
        *_audit_users(),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("journal_entry_id", UUID, nullable=True),
        sa.Column("reversal_journal_entry_id", UUID, nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_gain_base", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("warnings", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["reversal_journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fx_revaluation_runs_tenant_id_status", "fx_revaluation_runs", ["tenant_id", "status"]
    )
    op.create_index(
        "uq_fx_revaluation_runs_open",
        "fx_revaluation_runs",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'POSTED' AND deleted_at IS NULL"),
    )

    op.create_table(
        "fx_revaluation_lines",
        _pk(),
        _tenant(),
        *_timestamps(),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("exposure_kind", sa.String(length=10), nullable=False),
        sa.Column("currency_id", UUID, nullable=False),
        sa.Column("party_type", sa.String(length=20), nullable=True),
        sa.Column("party_id", UUID, nullable=True),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("foreign_balance", MONEY, nullable=False),
        sa.Column("closing_rate", RATE, nullable=False),
        sa.Column("book_base", MONEY, nullable=False),
        sa.Column("revalued_base", MONEY, nullable=False),
        sa.Column("gain_base", MONEY, nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["fx_revaluation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fx_revaluation_lines_run", "fx_revaluation_lines", ["tenant_id", "run_id"])

    op.create_table(
        "report_export_jobs",
        _pk(),
        _tenant(),
        *_timestamps(),
        *_audit_users(),
        sa.Column("report_key", sa.String(length=60), nullable=False),
        sa.Column("export_format", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("params", JSONB, nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=True),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_report_export_jobs_tenant_status", "report_export_jobs", ["tenant_id", "status"]
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
    op.drop_index("ix_report_export_jobs_tenant_status", table_name="report_export_jobs")
    op.drop_table("report_export_jobs")
    op.drop_index("ix_fx_revaluation_lines_run", table_name="fx_revaluation_lines")
    op.drop_table("fx_revaluation_lines")
    op.drop_index("uq_fx_revaluation_runs_open", table_name="fx_revaluation_runs")
    op.drop_index("ix_fx_revaluation_runs_tenant_id_status", table_name="fx_revaluation_runs")
    op.drop_table("fx_revaluation_runs")
    op.drop_table("recurring_generations")
    op.drop_index("ix_recurring_templates_tenant_id_next_run", table_name="recurring_templates")
    op.drop_index("ix_recurring_templates_tenant_id_status", table_name="recurring_templates")
    op.drop_table("recurring_templates")
    op.drop_index("ix_budget_lines_tenant_id_budget_id", table_name="budget_lines")
    op.drop_table("budget_lines")
    op.drop_index("ix_budgets_tenant_id_fiscal_year", table_name="budgets")
    op.drop_index("ix_budgets_tenant_id_status", table_name="budgets")
    op.drop_table("budgets")
