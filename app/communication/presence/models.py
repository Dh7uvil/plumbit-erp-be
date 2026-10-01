"""User presence ORM model."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantModel


class UserPresence(TenantModel):
    __tablename__ = "user_presence"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_user_presence_tenant_user"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'OFFLINE'")
    )
    custom_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
