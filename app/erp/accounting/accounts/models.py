"""Chart of accounts ORM model."""

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin


class Account(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """Tenant chart-of-accounts row. Group accounts are never postable."""

    __tablename__ = "accounts"
    __table_args__ = (
        Index(
            "uq_accounts_tenant_id_code_active",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_accounts_tenant_id_system_role_active",
            "tenant_id",
            "system_role",
            unique=True,
            postgresql_where=text("system_role IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index("ix_accounts_tenant_id_parent_id", "tenant_id", "parent_id"),
        Index("ix_accounts_tenant_id_account_type", "tenant_id", "account_type"),
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    account_subtype: Mapped[str] = mapped_column(String(40), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_group: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    system_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
