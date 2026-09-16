"""User notification preference ORM model."""

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantModel


class UserNotificationPreference(TenantModel):
    """Per-user channel toggles. One row per user; missing row means defaults."""

    __tablename__ = "user_notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            name="uq_user_notification_preferences_tenant_user",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
