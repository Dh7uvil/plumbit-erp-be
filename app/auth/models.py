"""Access-management ORM models."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


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
        ForeignKey("employees.id", ondelete="SET NULL"),
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


class Address(
    UUIDPrimaryKeyMixin,
    TenantScopedMixin,
    TimestampMixin,
    SoftDeleteMixin,
    Base,
):
    """Postal address used by branches and other org records."""

    __tablename__ = "addresses"

    address_type: Mapped[str] = mapped_column(String(30), nullable=False)
    address_line_1: Mapped[str | None] = mapped_column(String(250), nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(String(250), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(30), nullable=True)


class Branch(
    UUIDPrimaryKeyMixin,
    TenantScopedMixin,
    TimestampMixin,
    SoftDeleteMixin,
    Base,
):
    """Physical operating location within a tenant."""

    __tablename__ = "branches"
    __table_args__ = (
        Index(
            "uq_branches_tenant_id_code_active",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    address_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("addresses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    default_currency_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )


class Department(
    UUIDPrimaryKeyMixin,
    TenantScopedMixin,
    TimestampMixin,
    SoftDeleteMixin,
    Base,
):
    """Org unit belonging to a branch."""

    __tablename__ = "departments"
    __table_args__ = (
        Index(
            "uq_departments_tenant_id_code_active",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    branch_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    manager_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class Employee(
    UUIDPrimaryKeyMixin,
    TenantScopedMixin,
    TimestampMixin,
    SoftDeleteMixin,
    Base,
):
    """HR profile optionally linked to a login user."""

    __tablename__ = "employees"
    __table_args__ = (
        Index(
            "uq_employees_tenant_id_employee_code_active",
            "tenant_id",
            "employee_code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    employee_code: Mapped[str] = mapped_column(String(50), nullable=False)
    branch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    department_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    designation: Mapped[str | None] = mapped_column(String(150), nullable=True)
    joining_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )
