"""Add source document link on vouchers and cost sheets.

Revision ID: f1a2b3c4d190
Revises: e0f1a2b3c189
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "f1a2b3c4d190"
down_revision: str | None = "e0f1a2b3c189"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vouchers",
        sa.Column("source_document_type", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "vouchers",
        sa.Column("source_document_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_vouchers_tenant_id_source_document",
        "vouchers",
        ["tenant_id", "source_document_type", "source_document_id"],
    )

    op.add_column(
        "cost_sheets",
        sa.Column("source_document_type", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "cost_sheets",
        sa.Column("source_document_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_cost_sheets_tenant_id_source_document",
        "cost_sheets",
        ["tenant_id", "source_document_type", "source_document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cost_sheets_tenant_id_source_document", table_name="cost_sheets")
    op.drop_column("cost_sheets", "source_document_id")
    op.drop_column("cost_sheets", "source_document_type")
    op.drop_index("ix_vouchers_tenant_id_source_document", table_name="vouchers")
    op.drop_column("vouchers", "source_document_id")
    op.drop_column("vouchers", "source_document_type")
