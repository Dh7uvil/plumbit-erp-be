"""CRM phase 9: opportunity links, closed_at, lead lost reason.

Revision ID: n0i1j2k3l456
Revises: m9h0i1j2k345
Create Date: 2026-09-29 23:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "n0i1j2k3l456"
down_revision: str | None = "m9h0i1j2k345"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "sales_orders",
        sa.Column("opportunity_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_sales_orders_opportunity_id",
        "sales_orders",
        "crm_opportunities",
        ["opportunity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_sales_orders_tenant_id_opportunity_id",
        "sales_orders",
        ["tenant_id", "opportunity_id"],
        unique=False,
    )

    op.add_column(
        "sales_invoices",
        sa.Column("opportunity_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_sales_invoices_opportunity_id",
        "sales_invoices",
        "crm_opportunities",
        ["opportunity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_sales_invoices_tenant_id_opportunity_id",
        "sales_invoices",
        ["tenant_id", "opportunity_id"],
        unique=False,
    )

    op.add_column(
        "crm_opportunities",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "crm_leads",
        sa.Column("lost_reason_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_crm_leads_lost_reason_id",
        "crm_leads",
        "crm_lost_reasons",
        ["lost_reason_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_crm_leads_lost_reason_id", "crm_leads", type_="foreignkey")
    op.drop_column("crm_leads", "lost_reason_id")

    op.drop_column("crm_opportunities", "closed_at")

    op.drop_index("ix_sales_invoices_tenant_id_opportunity_id", table_name="sales_invoices")
    op.drop_constraint("fk_sales_invoices_opportunity_id", "sales_invoices", type_="foreignkey")
    op.drop_column("sales_invoices", "opportunity_id")

    op.drop_index("ix_sales_orders_tenant_id_opportunity_id", table_name="sales_orders")
    op.drop_constraint("fk_sales_orders_opportunity_id", "sales_orders", type_="foreignkey")
    op.drop_column("sales_orders", "opportunity_id")
