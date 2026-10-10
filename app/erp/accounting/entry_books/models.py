"""Entry book configuration (legacy Winsoft entry book master)."""

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScopedMixin, UUIDPrimaryKeyMixin


class EntryBook(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    __tablename__ = "entry_books"
    __table_args__ = (
        UniqueConstraint("tenant_id", "voucher_type", name="uq_entry_books_tenant_type"),
    )

    voucher_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    series_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    default_account_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
