"""Extended communication ORM models."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantModel


class ChatUserMapping(TenantModel):
    __tablename__ = "chat_user_mapping"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_chat_user_mapping_tenant_user"),
        UniqueConstraint(
            "tenant_id", "agora_user_id", name="uq_chat_user_mapping_tenant_agora_user"
        ),
        UniqueConstraint("tenant_id", "rtc_uid", name="uq_chat_user_mapping_tenant_rtc_uid"),
        Index("ix_chat_user_mapping_tenant_user", "tenant_id", "user_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    agora_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rtc_uid: Mapped[int] = mapped_column(Integer, nullable=False)


class ChatMessageRead(TenantModel):
    __tablename__ = "chat_message_reads"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "message_id",
            "user_id",
            name="uq_chat_message_reads_tenant_message_user",
        ),
        Index("ix_chat_message_reads_tenant_message", "tenant_id", "message_id"),
    )

    message_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ChatMessageReaction(TenantModel):
    __tablename__ = "chat_message_reactions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "message_id",
            "user_id",
            "emoji",
            name="uq_chat_message_reactions_tenant_message_user_emoji",
        ),
        Index("ix_chat_message_reactions_tenant_message", "tenant_id", "message_id"),
    )

    message_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    emoji: Mapped[str] = mapped_column(String(32), nullable=False)


class ChatMessageMention(TenantModel):
    __tablename__ = "chat_message_mentions"
    __table_args__ = (
        Index("ix_chat_message_mentions_tenant_message", "tenant_id", "message_id"),
        Index("ix_chat_message_mentions_tenant_user", "tenant_id", "mentioned_user_id"),
    )

    message_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    mentioned_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    is_everyone: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class ChatMessageAttachment(TenantModel):
    __tablename__ = "chat_message_attachments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "message_id",
            "attachment_id",
            name="uq_chat_message_attachments_tenant_message_attachment",
        ),
        Index("ix_chat_message_attachments_tenant_message", "tenant_id", "message_id"),
    )

    message_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    attachment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("attachments.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    waveform: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    scan_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'PENDING'")
    )


class ChatPinnedMessage(TenantModel):
    __tablename__ = "chat_pinned_messages"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "message_id",
            name="uq_chat_pinned_messages_tenant_conversation_message",
        ),
        Index("ix_chat_pinned_messages_tenant_conversation", "tenant_id", "conversation_id"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    pinned_by: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    pinned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ChatSavedMessage(TenantModel):
    __tablename__ = "chat_saved_messages"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "message_id",
            name="uq_chat_saved_messages_tenant_user_message",
        ),
        Index("ix_chat_saved_messages_tenant_user", "tenant_id", "user_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CallEvent(TenantModel):
    __tablename__ = "call_events"
    __table_args__ = (Index("ix_call_events_tenant_call", "tenant_id", "call_id"),)

    call_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'API'"))


class ChatNotificationSettings(TenantModel):
    __tablename__ = "chat_notification_settings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            name="uq_chat_notification_settings_tenant_user",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_notifications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    group_notifications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    call_notifications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    sound_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    desktop_notifications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    mobile_notifications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
