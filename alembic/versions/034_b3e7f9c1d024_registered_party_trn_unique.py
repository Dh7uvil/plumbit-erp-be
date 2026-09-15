"""Enforce registered party TRN uniqueness.

Revision ID: b3e7f9c1d024
Revises: a2d4f6b8c901
Create Date: 2026-09-15 13:35:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3e7f9c1d024"
down_revision: str | None = "a2d4f6b8c901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY tenant_id, trn
                           ORDER BY created_at ASC, id ASC
                       ) AS rn
                FROM customers
                WHERE deleted_at IS NULL
                  AND trn IS NOT NULL
                  AND tax_treatment = 'REGISTERED'
            )
            UPDATE customers AS c
            SET trn = NULL,
                tax_treatment = 'UNREGISTERED'
            FROM ranked
            WHERE c.id = ranked.id
              AND ranked.rn > 1
            """
        )
    )
    op.create_index(
        "uq_customers_tenant_id_trn_registered_active",
        "customers",
        ["tenant_id", "trn"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND trn IS NOT NULL AND tax_treatment = 'REGISTERED'"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_customers_tenant_id_trn_registered_active", table_name="customers")
