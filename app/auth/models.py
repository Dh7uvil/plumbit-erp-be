"""Access-management ORM models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Top-level tenant; not itself tenant-scoped."""

    __tablename__ = "tenants"
    __table_args__ = (UniqueConstraint("code", name="uq_tenants_code"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    timezone: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        server_default=text("'UTC'"),
    )
    default_currency_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )


class User(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Tenant-owned login identity."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_id_email"),)

    employee_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class Role(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Named bundle of permissions within a tenant."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_id_name"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system_role: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )


class Permission(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Canonical ``module.resource.action`` grant stored per tenant."""

    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "module",
            "resource",
            "action",
            name="uq_permissions_tenant_module_resource_action",
        ),
    )

    module: Mapped[str] = mapped_column(String(100), nullable=False)
    resource: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)


class UserRole(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Assignment of a role to a user within a tenant."""

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "role_id",
            name="uq_user_roles_tenant_id_user_id_role_id",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class RolePermission(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Assignment of a permission to a role within a tenant."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "role_id",
            "permission_id",
            name="uq_role_permissions_tenant_role_permission",
        ),
    )

    role_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class RefreshToken(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Persisted refresh-token identifier used for rotation and logout."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (UniqueConstraint("jti", name="uq_refresh_tokens_jti"),)

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    jti: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
