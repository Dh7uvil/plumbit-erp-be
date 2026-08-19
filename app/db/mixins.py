"""Reusable SQLAlchemy model mixins."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class UUIDPrimaryKeyMixin:
    """Provide a PostgreSQL-generated UUID primary key."""

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """Provide database-managed, timezone-aware audit timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TenantScopedMixin:
    """Mark a model as tenant-owned without declaring a tenants table."""

    tenant_fk_target: ClassVar[str] = "tenants.id"

    @declared_attr
    def tenant_id(cls) -> Mapped[UUID]:
        """Reference the tenant table by name for deferred model resolution."""

        return mapped_column(
            PostgreSQLUUID(as_uuid=True),
            ForeignKey(cls.tenant_fk_target, ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )


class AuditUserMixin:
    """Track the users responsible for creating and updating a row."""

    created_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class SoftDeleteMixin:
    """Provide a nullable deletion timestamp."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )


class IsActiveMixin:
    """Provide a database-default active flag."""

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
