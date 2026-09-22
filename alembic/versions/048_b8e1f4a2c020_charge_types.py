"""Charge type master for import/export costing.

Revision ID: b8e1f4a2c020
Revises: a7b0c3d6e019
Create Date: 2026-09-22 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b8e1f4a2c020"
down_revision: str | None = "a7b0c3d6e019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "charge_types",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_inventoriable", sa.Boolean(), nullable=False),
        sa.Column("default_account_id", UUID, nullable=False),
        sa.Column("allocation_basis", sa.String(length=20), nullable=True),
        sa.Column("default_tax_id", UUID, nullable=True),
        sa.Column(
            "applies_to",
            sa.String(length=20),
            server_default=sa.text("'BOTH'"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["default_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["default_tax_id"], ["taxes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_charge_types_tenant_id", "charge_types", ["tenant_id"], unique=False)
    op.create_index(
        "ix_charge_types_default_account_id", "charge_types", ["default_account_id"], unique=False
    )
    op.create_index(
        "ix_charge_types_default_tax_id", "charge_types", ["default_tax_id"], unique=False
    )
    op.create_index(
        "uq_charge_types_tenant_id_code_active",
        "charge_types",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_charge_types_tenant_id_code_active", table_name="charge_types")
    op.drop_index("ix_charge_types_default_tax_id", table_name="charge_types")
    op.drop_index("ix_charge_types_default_account_id", table_name="charge_types")
    op.drop_index("ix_charge_types_tenant_id", table_name="charge_types")
    op.drop_table("charge_types")
