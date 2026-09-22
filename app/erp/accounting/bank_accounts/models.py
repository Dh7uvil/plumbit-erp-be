"""Bank account ORM — identity and reconciliation metadata for a GL bank account."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MONEY_PRECISION, MONEY_SCALE
from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin

_MONEY = Numeric(MONEY_PRECISION, MONEY_SCALE)


class BankAccount(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """One-to-one extension of a postable BANK chart account."""

    __tablename__ = "bank_accounts"
    __table_args__ = (
        Index(
            "uq_bank_accounts_tenant_id_account_id_active",
            "tenant_id",
            "account_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_bank_accounts_tenant_id_is_active", "tenant_id", "is_active"),
    )

    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    account_name: Mapped[str] = mapped_column(String(150), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(150), nullable=False)
    branch_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    iban: Mapped[str | None] = mapped_column(String(50), nullable=True)
    swift: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    opening_balance: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    opening_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
