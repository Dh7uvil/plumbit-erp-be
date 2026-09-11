"""Transactional outbox table and identity.outbox_event permissions.

Revision ID: e3b8d5f0c124
Revises: d2a7c4e9b013
Create Date: 2026-09-09 12:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e3b8d5f0c124"
down_revision: str | Sequence[str] | None = "d2a7c4e9b013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
_OUTBOX_ACTIONS = ("read", "retry")


def upgrade() -> None:
    """Create outbox_events and grant Superadmin identity.outbox_event.*."""

    op.create_table(
        "outbox_events",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("aggregate_type", sa.String(length=50), nullable=False),
        sa.Column("aggregate_id", UUID, nullable=False),
        sa.Column("dedupe_key", sa.String(length=120), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("8"), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=80), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_events_tenant_id", "outbox_events", ["tenant_id"], unique=False)
    op.create_index(
        "ix_outbox_events_status_available_at",
        "outbox_events",
        ["status", "available_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('PENDING', 'FAILED')"),
    )
    op.create_index(
        "uq_outbox_events_tenant_event_dedupe",
        "outbox_events",
        ["tenant_id", "event_type", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    op.create_index(
        "ix_outbox_events_tenant_aggregate",
        "outbox_events",
        ["tenant_id", "aggregate_type", "aggregate_id"],
        unique=False,
    )
    _backfill_permissions("identity", "outbox_event", _OUTBOX_ACTIONS)


def downgrade() -> None:
    """Drop outbox_events and outbox_event catalog rows."""

    op.execute(
        sa.text(
            """
            DELETE FROM permissions
            WHERE module = 'identity'
              AND resource = 'outbox_event'
              AND action IN ('read', 'retry')
            """
        )
    )
    op.drop_index("ix_outbox_events_tenant_aggregate", table_name="outbox_events")
    op.drop_index("uq_outbox_events_tenant_event_dedupe", table_name="outbox_events")
    op.drop_index("ix_outbox_events_status_available_at", table_name="outbox_events")
    op.drop_index("ix_outbox_events_tenant_id", table_name="outbox_events")
    op.drop_table("outbox_events")


def _backfill_permissions(module: str, resource: str, actions: tuple[str, ...]) -> None:
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    for (tenant_id,) in tenants:
        existing = bind.execute(
            sa.text(
                "SELECT module, resource, action FROM permissions WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).fetchall()
        existing_keys = {(row.module, row.resource, row.action) for row in existing}
        for action in actions:
            key = (module, resource, action)
            if key in existing_keys:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO permissions (tenant_id, module, resource, action)
                    VALUES (:tenant_id, :module, :resource, :action)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "module": module,
                    "resource": resource,
                    "action": action,
                },
            )

        admin = bind.execute(
            sa.text(
                """
                SELECT id FROM roles
                WHERE tenant_id = :tenant_id
                  AND name = 'Superadmin'
                  AND is_system_role IS TRUE
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if admin is None:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO role_permissions (tenant_id, role_id, permission_id)
                SELECT :tenant_id, :role_id, p.id
                FROM permissions p
                WHERE p.tenant_id = :tenant_id
                  AND p.module = :module
                  AND p.resource = :resource
                  AND p.action IN ('read', 'retry')
                  AND NOT EXISTS (
                    SELECT 1
                    FROM role_permissions rp
                    WHERE rp.tenant_id = :tenant_id
                      AND rp.role_id = :role_id
                      AND rp.permission_id = p.id
                  )
                """
            ),
            {
                "tenant_id": tenant_id,
                "role_id": admin.id,
                "module": module,
                "resource": resource,
            },
        )
