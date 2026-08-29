"""rename system Admin role to Superadmin

Revision ID: c3d9e8f1a204
Revises: f8a4b1c6d937
Create Date: 2026-08-27 11:35:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d9e8f1a204"
down_revision: str | Sequence[str] | None = "f8a4b1c6d937"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename the system Admin role to Superadmin on existing tenants."""

    op.execute(
        sa.text(
            """
            UPDATE roles
            SET name = 'Superadmin',
                description = 'Superadmin with all catalog permissions'
            WHERE name = 'Admin'
              AND is_system_role IS TRUE
            """
        )
    )


def downgrade() -> None:
    """Restore the previous system Admin role name."""

    op.execute(
        sa.text(
            """
            UPDATE roles
            SET name = 'Admin',
                description = 'System administrator with all catalog permissions'
            WHERE name = 'Superadmin'
              AND is_system_role IS TRUE
            """
        )
    )
