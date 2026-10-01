"""Communication extended tables and columns.

Revision ID: t4u5v6w7x890
Revises: s3t4u5v6w789
Create Date: 2026-09-30 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "t4u5v6w7x890"
down_revision: str | None = "s3t4u5v6w789"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.execute(
        sa.text(
            "CREATE SEQUENCE IF NOT EXISTS chat_rtc_uid_seq START WITH 1000 INCREMENT BY 1"
        )
    )

    op.create_table(
        "chat_user_mapping",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("agora_user_id", sa.String(length=64), nullable=False),
        sa.Column("rtc_uid", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_chat_user_mapping_tenant_user"),
        sa.UniqueConstraint("tenant_id", "agora_user_id", name="uq_chat_user_mapping_tenant_agora_user"),
        sa.UniqueConstraint("tenant_id", "rtc_uid", name="uq_chat_user_mapping_tenant_rtc_uid"),
    )
    op.create_index("ix_chat_user_mapping_tenant_user", "chat_user_mapping", ["tenant_id", "user_id"])

    op.create_table(
        "chat_message_reads",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("message_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "message_id", "user_id", name="uq_chat_message_reads_tenant_message_user"),
    )
    op.create_index(
        "ix_chat_message_reads_tenant_message",
        "chat_message_reads",
        ["tenant_id", "message_id"],
    )

    op.create_table(
        "chat_message_reactions",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("message_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("emoji", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "message_id",
            "user_id",
            "emoji",
            name="uq_chat_message_reactions_tenant_message_user_emoji",
        ),
    )
    op.create_index(
        "ix_chat_message_reactions_tenant_message",
        "chat_message_reactions",
        ["tenant_id", "message_id"],
    )

    op.create_table(
        "chat_message_mentions",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("message_id", UUID, nullable=False),
        sa.Column("mentioned_user_id", UUID, nullable=True),
        sa.Column("is_everyone", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mentioned_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_message_mentions_tenant_message",
        "chat_message_mentions",
        ["tenant_id", "message_id"],
    )
    op.create_index(
        "ix_chat_message_mentions_tenant_user",
        "chat_message_mentions",
        ["tenant_id", "mentioned_user_id"],
    )

    op.create_table(
        "chat_message_attachments",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("message_id", UUID, nullable=False),
        sa.Column("attachment_id", UUID, nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("waveform", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("thumbnail_key", sa.String(length=512), nullable=True),
        sa.Column("scan_status", sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attachment_id"], ["attachments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "message_id",
            "attachment_id",
            name="uq_chat_message_attachments_tenant_message_attachment",
        ),
    )
    op.create_index(
        "ix_chat_message_attachments_tenant_message",
        "chat_message_attachments",
        ["tenant_id", "message_id"],
    )

    op.create_table(
        "chat_pinned_messages",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("message_id", UUID, nullable=False),
        sa.Column("pinned_by", UUID, nullable=False),
        sa.Column("pinned_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pinned_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "message_id",
            name="uq_chat_pinned_messages_tenant_conversation_message",
        ),
    )
    op.create_index(
        "ix_chat_pinned_messages_tenant_conversation",
        "chat_pinned_messages",
        ["tenant_id", "conversation_id"],
    )

    op.create_table(
        "chat_saved_messages",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("message_id", UUID, nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "message_id",
            name="uq_chat_saved_messages_tenant_user_message",
        ),
    )
    op.create_index(
        "ix_chat_saved_messages_tenant_user",
        "chat_saved_messages",
        ["tenant_id", "user_id"],
    )

    op.create_table(
        "call_events",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("call_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source", sa.String(length=20), server_default=sa.text("'API'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_call_events_tenant_call", "call_events", ["tenant_id", "call_id"])

    op.create_table(
        "chat_notification_settings",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("message_notifications", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("group_notifications", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("call_notifications", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sound_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("desktop_notifications", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("mobile_notifications", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            name="uq_chat_notification_settings_tenant_user",
        ),
    )

    op.add_column(
        "messages",
        sa.Column("forwarded_from_message_id", UUID, nullable=True),
    )
    op.create_foreign_key(
        "fk_messages_forwarded_from",
        "messages",
        "messages",
        ["forwarded_from_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE messages
            ADD COLUMN search_vector tsvector
            GENERATED ALWAYS AS (
                CASE WHEN body IS NOT NULL AND deleted_at IS NULL
                THEN to_tsvector('simple', body)
                ELSE NULL END
            ) STORED
            """
        )
    )
    op.create_index(
        "ix_messages_search_vector",
        "messages",
        ["search_vector"],
        postgresql_using="gin",
    )

    op.add_column(
        "conversations",
        sa.Column("max_members", sa.Integer(), server_default=sa.text("256"), nullable=False),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "only_admins_can_edit_info",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("context_entity_type", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("context_entity_id", UUID, nullable=True),
    )
    op.create_index(
        "ix_conversations_tenant_context",
        "conversations",
        ["tenant_id", "context_entity_type", "context_entity_id"],
    )

    op.add_column(
        "conversation_participants",
        sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True),
    )

    _backfill_catalog_permissions()


def downgrade() -> None:
    op.drop_column("conversation_participants", "muted_until")
    op.drop_index("ix_conversations_tenant_context", table_name="conversations")
    op.drop_column("conversations", "context_entity_id")
    op.drop_column("conversations", "context_entity_type")
    op.drop_column("conversations", "only_admins_can_edit_info")
    op.drop_column("conversations", "max_members")
    op.drop_index("ix_messages_search_vector", table_name="messages")
    op.execute(sa.text("ALTER TABLE messages DROP COLUMN IF EXISTS search_vector"))
    op.drop_constraint("fk_messages_forwarded_from", "messages", type_="foreignkey")
    op.drop_column("messages", "forwarded_from_message_id")
    op.drop_table("chat_notification_settings")
    op.drop_index("ix_call_events_tenant_call", table_name="call_events")
    op.drop_table("call_events")
    op.drop_index("ix_chat_saved_messages_tenant_user", table_name="chat_saved_messages")
    op.drop_table("chat_saved_messages")
    op.drop_index("ix_chat_pinned_messages_tenant_conversation", table_name="chat_pinned_messages")
    op.drop_table("chat_pinned_messages")
    op.drop_index("ix_chat_message_attachments_tenant_message", table_name="chat_message_attachments")
    op.drop_table("chat_message_attachments")
    op.drop_index("ix_chat_message_mentions_tenant_user", table_name="chat_message_mentions")
    op.drop_index("ix_chat_message_mentions_tenant_message", table_name="chat_message_mentions")
    op.drop_table("chat_message_mentions")
    op.drop_index("ix_chat_message_reactions_tenant_message", table_name="chat_message_reactions")
    op.drop_table("chat_message_reactions")
    op.drop_index("ix_chat_message_reads_tenant_message", table_name="chat_message_reads")
    op.drop_table("chat_message_reads")
    op.drop_index("ix_chat_user_mapping_tenant_user", table_name="chat_user_mapping")
    op.drop_table("chat_user_mapping")
    op.execute(sa.text("DROP SEQUENCE IF EXISTS chat_rtc_uid_seq"))


def _backfill_catalog_permissions() -> None:
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    catalog = parsed_catalog_permissions()

    for (tenant_id,) in tenants:
        existing = bind.execute(
            sa.text(
                "SELECT module, resource, action FROM permissions WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).fetchall()
        existing_keys = {(row.module, row.resource, row.action) for row in existing}
        for parsed in catalog:
            key = (parsed.module, parsed.resource, parsed.action)
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
                    "module": parsed.module,
                    "resource": parsed.resource,
                    "action": parsed.action,
                },
            )

        admin = bind.execute(
            sa.text(
                """
                SELECT id FROM roles
                WHERE tenant_id = :tenant_id
                  AND is_system_role = true
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        if admin is not None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO role_permissions (tenant_id, role_id, permission_id)
                    SELECT :tenant_id, :role_id, p.id
                    FROM permissions p
                    WHERE p.tenant_id = :tenant_id
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
