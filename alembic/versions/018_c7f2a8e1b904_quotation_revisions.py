"""Quotation revision_number and quotation_revisions snapshots.

Revision ID: c7f2a8e1b904
Revises: b6e1d9f3c824
Create Date: 2026-09-09 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c7f2a8e1b904"
down_revision: str | Sequence[str] | None = "b6e1d9f3c824"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    """Add quotation revision columns and the immutable snapshot table."""

    op.add_column(
        "quotations",
        sa.Column("revision_number", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "quotations",
        sa.Column("revised_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "quotation_revisions",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("quotation_id", UUID, nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("quote_number", sa.String(length=40), nullable=False),
        sa.Column("status_at_revision", sa.String(length=30), nullable=False),
        sa.Column("header", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("lines", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision_reason", sa.Text(), nullable=False),
        sa.Column("revised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revised_by", UUID, nullable=True),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["quotation_id"], ["quotations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revised_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "quotation_id",
            "revision_number",
            name="uq_quotation_revisions_quotation_id_revision_number",
        ),
    )
    op.create_index("ix_quotation_revisions_tenant_id", "quotation_revisions", ["tenant_id"])
    op.create_index(
        "ix_quotation_revisions_tenant_id_quotation_id",
        "quotation_revisions",
        ["tenant_id", "quotation_id"],
    )


def downgrade() -> None:
    """Drop quotation revision history."""

    op.drop_index(
        "ix_quotation_revisions_tenant_id_quotation_id",
        table_name="quotation_revisions",
    )
    op.drop_index("ix_quotation_revisions_tenant_id", table_name="quotation_revisions")
    op.drop_table("quotation_revisions")
    op.drop_column("quotations", "revised_at")
    op.drop_column("quotations", "revision_number")
