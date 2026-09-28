"""Add task_type and parent_id to tasks.

Revision ID: c9d0e1f2a305
Revises: b7c8d9e0f194
Create Date: 2026-09-28 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c9d0e1f2a305"
down_revision: str | None = "b7c8d9e0f194"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "task_type",
            sa.String(length=20),
            server_default=sa.text("'TASK'"),
            nullable=False,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tasks_parent_id_tasks",
        "tasks",
        "tasks",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tasks_tenant_parent", "tasks", ["tenant_id", "parent_id"], unique=False)
    op.create_index("ix_tasks_tenant_type", "tasks", ["tenant_id", "task_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tasks_tenant_type", table_name="tasks")
    op.drop_index("ix_tasks_tenant_parent", table_name="tasks")
    op.drop_constraint("fk_tasks_parent_id_tasks", "tasks", type_="foreignkey")
    op.drop_column("tasks", "parent_id")
    op.drop_column("tasks", "task_type")
