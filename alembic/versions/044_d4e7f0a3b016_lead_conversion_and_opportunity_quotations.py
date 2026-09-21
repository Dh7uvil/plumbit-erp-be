"""Lead conversion quotations link.

Revision ID: d4e7f0a3b016
Revises: c3d6e9f2a015
Create Date: 2026-09-21 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d4e7f0a3b016"
down_revision: str | None = "c3d6e9f2a015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "quotations",
        sa.Column("opportunity_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_quotations_opportunity_id",
        "quotations",
        "crm_opportunities",
        ["opportunity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_quotations_tenant_id_opportunity_id",
        "quotations",
        ["tenant_id", "opportunity_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_quotations_tenant_id_opportunity_id", table_name="quotations")
    op.drop_constraint("fk_quotations_opportunity_id", "quotations", type_="foreignkey")
    op.drop_column("quotations", "opportunity_id")
