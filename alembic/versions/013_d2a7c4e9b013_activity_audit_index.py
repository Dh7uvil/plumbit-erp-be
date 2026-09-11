"""Add audit log tenant/entity index for per-record activity feeds.

Revision ID: d2a7c4e9b013
Revises: c0e5a9b4d683
Create Date: 2026-09-09 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2a7c4e9b013"
down_revision: str | Sequence[str] | None = "c0e5a9b4d683"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Index audit_logs for per-record activity queries."""

    op.execute(
        sa.text(
            """
            CREATE INDEX ix_audit_logs_tenant_entity
            ON audit_logs (tenant_id, entity_type, entity_id, created_at DESC)
            """
        )
    )


def downgrade() -> None:
    """Drop the activity feed index."""

    op.drop_index("ix_audit_logs_tenant_entity", table_name="audit_logs")
