"""Posted write-off rows with linked system journals."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MONEY_PRECISION, MONEY_SCALE
from app.db.base import TenantModel

_MONEY = Numeric(MONEY_PRECISION, MONEY_SCALE)


class InvoiceWriteOff(TenantModel):
    __tablename__ = "invoice_write_offs"
    __table_args__ = (
        Index(
            "ix_invoice_write_offs_tenant_invoice",
            "tenant_id",
            "document_kind",
            "invoice_id",
        ),
    )

    document_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    invoice_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    base_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    write_off_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expense_account_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    journal_entry_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    reversal_journal_entry_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
