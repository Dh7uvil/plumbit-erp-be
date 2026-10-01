"""Communication core tables and permissions.

Revision ID: s3t4u5v6w789
Revises: q2r3s4t5u678
Create Date: 2026-09-30 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import parsed_catalog_permissions

revision: str = "s3t4u5v6w789"
down_revision: str | None = "q2r3s4t5u678"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_attachment_id", UUID, nullable=True),
        sa.Column("direct_key", sa.String(length=73), nullable=True),
        sa.Column("channel_name", sa.String(length=64), nullable=False),
        sa.Column("message_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_message_id", UUID, nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("only_admins_can_post", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["image_attachment_id"], ["attachments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_conversations_tenant_direct_key_active",
        "conversations",
        ["tenant_id", "direct_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND kind = 'DIRECT'"),
    )
    op.create_index(
        "uq_conversations_tenant_channel_name_active",
        "conversations",
        ["tenant_id", "channel_name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_conversations_tenant_last_message_at",
        "conversations",
        ["tenant_id", "last_message_at"],
    )

    op.create_table(
        "messages",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("sender_id", UUID, nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("system_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reply_to_message_id", UUID, nullable=True),
        sa.Column("client_message_id", sa.String(length=64), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reply_to_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_seq"),
        sa.UniqueConstraint(
            "conversation_id",
            "sender_id",
            "client_message_id",
            name="uq_messages_conversation_sender_client_id",
        ),
    )
    op.create_index(
        "ix_messages_tenant_conversation_seq_desc",
        "messages",
        ["tenant_id", "conversation_id", sa.text("seq DESC")],
    )
    op.create_index(
        "ix_messages_tenant_conversation_attachment_seq_desc",
        "messages",
        ["tenant_id", "conversation_id", sa.text("seq DESC")],
        postgresql_where=sa.text("kind = 'ATTACHMENT'"),
    )

    op.create_foreign_key(
        "fk_conversations_last_message",
        "conversations",
        "messages",
        ["last_message_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "conversation_participants",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("role", sa.String(length=20), server_default=sa.text("'MEMBER'"), nullable=False),
        sa.Column("added_by", UUID, nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_read_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_delivered_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_muted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("notification_level", sa.String(length=20), server_default=sa.text("'ALL'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "user_id",
            name="uq_conversation_participants_tenant_conversation_user",
        ),
    )
    op.create_index(
        "ix_conversation_participants_tenant_user",
        "conversation_participants",
        ["tenant_id", "user_id"],
    )

    op.create_table(
        "calls",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("channel_name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("initiated_by", UUID, nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'RINGING'"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(length=50), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["initiated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_calls_tenant_channel_name",
        "calls",
        ["tenant_id", "channel_name"],
        unique=True,
    )
    op.create_index("ix_calls_tenant_conversation", "calls", ["tenant_id", "conversation_id"])
    op.create_index("ix_calls_tenant_status", "calls", ["tenant_id", "status"])

    op.create_table(
        "call_participants",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("call_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("rtc_uid", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'RINGING'"), nullable=False),
        sa.Column("invited_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_audio_muted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_video_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_screen_sharing", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "call_id",
            "user_id",
            name="uq_call_participants_tenant_call_user",
        ),
    )

    op.create_table(
        "user_presence",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'OFFLINE'"), nullable=False),
        sa.Column("custom_status", sa.String(length=100), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_user_presence_tenant_user"),
    )

    _backfill_catalog_permissions()


def downgrade() -> None:
    op.drop_table("user_presence")
    op.drop_table("call_participants")
    op.drop_index("ix_calls_tenant_status", table_name="calls")
    op.drop_index("ix_calls_tenant_conversation", table_name="calls")
    op.drop_index("uq_calls_tenant_channel_name", table_name="calls")
    op.drop_table("calls")
    op.drop_index("ix_conversation_participants_tenant_user", table_name="conversation_participants")
    op.drop_table("conversation_participants")
    op.drop_constraint("fk_conversations_last_message", "conversations", type_="foreignkey")
    op.drop_index(
        "ix_messages_tenant_conversation_attachment_seq_desc",
        table_name="messages",
    )
    op.drop_index("ix_messages_tenant_conversation_seq_desc", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_tenant_last_message_at", table_name="conversations")
    op.drop_index("uq_conversations_tenant_channel_name_active", table_name="conversations")
    op.drop_index("uq_conversations_tenant_direct_key_active", table_name="conversations")
    op.drop_table("conversations")


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
