"""Currency and daily exchange-rate ORM models."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MONEY_PRECISION
from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin

EXCHANGE_RATE_SCALE = 6


class Currency(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """Tenant-owned currency master. Exactly one row may be the base currency."""

    __tablename__ = "currencies"
    __table_args__ = (
        Index(
            "uq_currencies_tenant_id_code_active",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_currencies_tenant_id_base_active",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_base IS TRUE AND deleted_at IS NULL"),
        ),
    )

    code: Mapped[str] = mapped_column(String(3), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    decimal_places: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2,
        server_default=text("2"),
    )
    is_base: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )


class ExchangeRate(AuditUserMixin, TenantModel):
    """Org-level daily FX rate: base units per 1 unit of the foreign currency."""

    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "from_currency_id",
            "to_currency_id",
            "effective_date",
            name="uq_exchange_rates_tenant_pair_date",
        ),
    )

    from_currency_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    to_currency_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    rate: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, EXCHANGE_RATE_SCALE),
        nullable=False,
    )
