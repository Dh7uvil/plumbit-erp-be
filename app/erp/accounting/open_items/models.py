"""Open-item matching rows shared by receipts, supplier payments, and credit/debit notes."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MONEY_PRECISION, MONEY_SCALE
from app.db.base import TenantModel

_MONEY = Numeric(MONEY_PRECISION, MONEY_SCALE)


class PaymentAllocation(TenantModel):
    """Subledger match from a payment or note onto an open item. Not a GL table."""

    __tablename__ = "payment_allocations"
    __table_args__ = (
        Index(
            "uq_payment_allocations_live_match",
            "tenant_id",
            "payment_type",
            "payment_id",
            "item_type",
            "item_id",
            unique=True,
            postgresql_where=text("reversed_at IS NULL"),
        ),
        Index(
            "ix_payment_allocations_tenant_payment",
            "tenant_id",
            "payment_type",
            "payment_id",
        ),
        Index(
            "ix_payment_allocations_tenant_item",
            "tenant_id",
            "item_type",
            "item_id",
        ),
    )

    payment_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payment_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    item_type: Mapped[str] = mapped_column(String(40), nullable=False)
    item_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    journal_entry_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
