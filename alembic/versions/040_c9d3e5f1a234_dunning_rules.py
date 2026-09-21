"""Dunning rules and reminder logs.

Revision ID: c9d3e5f1a234
Revises: b7e2c4d8a901
Create Date: 2026-09-21 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c9d3e5f1a234"
down_revision: str | None = "b7e2c4d8a901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "dunning_rules",
        sa.Column(
            "id",
            UUID,
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("days_offset", sa.Integer(), nullable=False),
        sa.Column("template_key", sa.String(40), nullable=False),
        sa.Column(
            "escalate",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
    )
    op.create_index("ix_dunning_rules_tenant_id", "dunning_rules", ["tenant_id"])
    op.create_index(
        "uq_dunning_rules_tenant_id_name_active",
        "dunning_rules",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "dunning_logs",
        sa.Column(
            "id",
            UUID,
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "sales_invoice_id",
            UUID,
            sa.ForeignKey("sales_invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dunning_rule_id",
            UUID,
            sa.ForeignKey("dunning_rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(20), server_default=sa.text("'EMAIL'"), nullable=False),
        sa.Column("recipient_email", sa.String(255), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_dunning_logs_tenant_id", "dunning_logs", ["tenant_id"])
    op.create_index(
        "ix_dunning_logs_tenant_invoice",
        "dunning_logs",
        ["tenant_id", "sales_invoice_id"],
    )
    op.create_index(
        "uq_dunning_logs_tenant_invoice_rule",
        "dunning_logs",
        ["tenant_id", "sales_invoice_id", "dunning_rule_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_dunning_logs_tenant_invoice_rule", table_name="dunning_logs")
    op.drop_index("ix_dunning_logs_tenant_invoice", table_name="dunning_logs")
    op.drop_index("ix_dunning_logs_tenant_id", table_name="dunning_logs")
    op.drop_table("dunning_logs")
    op.drop_index("uq_dunning_rules_tenant_id_name_active", table_name="dunning_rules")
    op.drop_index("ix_dunning_rules_tenant_id", table_name="dunning_rules")
    op.drop_table("dunning_rules")
