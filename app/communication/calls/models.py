"""Call ORM models."""

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
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantModel
from app.db.mixins import AuditUserMixin


class Call(AuditUserMixin, TenantModel):
    __tablename__ = "calls"
    __table_args__ = (
        Index(
            "uq_calls_tenant_channel_name",
            "tenant_id",
            "channel_name",
            unique=True,
        ),
        Index("ix_calls_tenant_conversation", "tenant_id", "conversation_id"),
        Index("ix_calls_tenant_status", "tenant_id", "status"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_name: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    initiated_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'RINGING'")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CallParticipant(TenantModel):
    __tablename__ = "call_participants"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "call_id",
            "user_id",
            name="uq_call_participants_tenant_call_user",
        ),
    )

    call_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    rtc_uid: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'RINGING'")
    )
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_audio_muted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_video_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_screen_sharing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
