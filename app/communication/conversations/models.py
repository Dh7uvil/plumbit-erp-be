"""Conversation ORM models."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin


class Conversation(AuditUserMixin, SoftDeleteTenantModel):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "uq_conversations_tenant_direct_key_active",
            "tenant_id",
            "direct_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND kind = 'DIRECT'"),
        ),
        Index(
            "uq_conversations_tenant_channel_name_active",
            "tenant_id",
            "channel_name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_conversations_tenant_last_message_at", "tenant_id", "last_message_at"),
        Index(
            "ix_conversations_tenant_context",
            "tenant_id",
            "context_entity_type",
            "context_entity_id",
        ),
    )

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_attachment_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("attachments.id", ondelete="SET NULL"),
        nullable=True,
    )
    direct_key: Mapped[str | None] = mapped_column(String(73), nullable=True)
    channel_name: Mapped[str] = mapped_column(String(64), nullable=False)
    message_seq: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    last_message_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL", use_alter=True, name="fk_conversations_last_message"),
        nullable=True,
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    only_admins_can_post: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    max_members: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("256")
    )
    only_admins_can_edit_info: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    context_entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    context_entity_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )


class ConversationParticipant(TenantModel):
    __tablename__ = "conversation_participants"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "user_id",
            name="uq_conversation_participants_tenant_conversation_user",
        ),
        Index("ix_conversation_participants_tenant_user", "tenant_id", "user_id"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'MEMBER'")
    )
    added_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_read_seq: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    last_delivered_seq: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    is_muted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    notification_level: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'ALL'")
    )
    muted_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
