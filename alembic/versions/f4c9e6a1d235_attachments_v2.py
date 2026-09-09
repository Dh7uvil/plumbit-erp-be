"""Attachment categories, thumbnails, and identity.attachment.update.

Revision ID: f4c9e6a1d235
Revises: e3b8d5f0c124
Create Date: 2026-09-09 12:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4c9e6a1d235"
down_revision: str | Sequence[str] | None = "e3b8d5f0c124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add category/thumbnail columns and grant attachment.update to Superadmin."""

    op.add_column("attachments", sa.Column("category", sa.String(length=40), nullable=True))
    op.add_column(
        "attachments",
        sa.Column("thumbnail_storage_key", sa.String(length=500), nullable=True),
    )
    op.add_column("attachments", sa.Column("image_width", sa.Integer(), nullable=True))
    op.add_column("attachments", sa.Column("image_height", sa.Integer(), nullable=True))
    op.create_index(
        "ix_attachments_tenant_entity_category",
        "attachments",
        ["tenant_id", "entity_type", "entity_id", "category"],
        unique=False,
    )
    _backfill_attachment_update()


def downgrade() -> None:
    """Drop attachment v2 columns and the update permission."""

    op.execute(
        sa.text(
            """
            DELETE FROM permissions
            WHERE module = 'identity'
              AND resource = 'attachment'
              AND action = 'update'
            """
        )
    )
    op.drop_index("ix_attachments_tenant_entity_category", table_name="attachments")
    op.drop_column("attachments", "image_height")
    op.drop_column("attachments", "image_width")
    op.drop_column("attachments", "thumbnail_storage_key")
    op.drop_column("attachments", "category")


def _backfill_attachment_update() -> None:
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    for (tenant_id,) in tenants:
        existing = bind.execute(
            sa.text(
                """
                SELECT id FROM permissions
                WHERE tenant_id = :tenant_id
                  AND module = 'identity'
                  AND resource = 'attachment'
                  AND action = 'update'
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if existing is None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO permissions (tenant_id, module, resource, action)
                    VALUES (:tenant_id, 'identity', 'attachment', 'update')
                    """
                ),
                {"tenant_id": tenant_id},
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
                  AND p.module = 'identity'
                  AND p.resource = 'attachment'
                  AND p.action = 'update'
                  AND NOT EXISTS (
                    SELECT 1
                    FROM role_permissions rp
                    WHERE rp.tenant_id = :tenant_id
                      AND rp.role_id = :role_id
                      AND rp.permission_id = p.id
                  )
                """
            ),
            {"tenant_id": tenant_id, "role_id": admin.id},
        )
