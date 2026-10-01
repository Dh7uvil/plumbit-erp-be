"""Message ORM model."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantModel


class Message(TenantModel):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "seq",
            name="uq_messages_conversation_seq",
        ),
        UniqueConstraint(
            "conversation_id",
            "sender_id",
            "client_message_id",
            name="uq_messages_conversation_sender_client_id",
        ),
        Index(
            "ix_messages_tenant_conversation_seq_desc",
            "tenant_id",
            "conversation_id",
            text("seq DESC"),
        ),
        Index(
            "ix_messages_tenant_conversation_attachment_seq_desc",
            "tenant_id",
            "conversation_id",
            text("seq DESC"),
            postgresql_where=text("kind = 'ATTACHMENT'"),
        ),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reply_to_message_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    forwarded_from_message_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
