"""Journal entry ORM models — the only GL tables."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import MONEY_PRECISION, MONEY_SCALE
from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin

_MONEY = Numeric(MONEY_PRECISION, MONEY_SCALE)
_RATE = Numeric(18, 6)


class JournalEntry(AuditUserMixin, SoftDeleteTenantModel):
    """Posted or draft journal. One POSTED row per (source_type, source_id)."""

    __tablename__ = "journal_entries"
    __table_args__ = (
        Index(
            "uq_journal_entries_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_journal_entries_tenant_source_posted",
            "tenant_id",
            "source_type",
            "source_id",
            unique=True,
            postgresql_where=text(
                "status = 'POSTED' AND deleted_at IS NULL "
                "AND source_type IS NOT NULL AND source_id IS NOT NULL"
            ),
        ),
        Index(
            "ix_journal_entries_tenant_id_entry_date_status",
            "tenant_id",
            "entry_date",
            "status",
        ),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    journal_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'MANUAL'")
    )
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    reversal_of_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reversed_by_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="RESTRICT"),
        nullable=True,
    )
    currency_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    exchange_rate: Mapped[Decimal] = mapped_column(_RATE, nullable=False, server_default=text("1"))
    branch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    narration: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    total_debit_base: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    total_credit_base: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )

    lines: Mapped[list["JournalEntryLine"]] = relationship(
        back_populates="journal_entry",
        cascade="all, delete-orphan",
        order_by="JournalEntryLine.line_number",
    )


class JournalEntryLine(TenantModel):
    """One GL line. AR/AP control accounts carry party_id and due_date."""

    __tablename__ = "journal_entry_lines"
    __table_args__ = (
        UniqueConstraint(
            "journal_entry_id",
            "line_number",
            name="uq_journal_entry_lines_header_line_number",
        ),
        Index(
            "ix_journal_entry_lines_tenant_account_journal",
            "tenant_id",
            "account_id",
            "journal_entry_id",
        ),
        Index(
            "ix_journal_entry_lines_tenant_party_due",
            "tenant_id",
            "party_type",
            "party_id",
            "due_date",
            postgresql_where=text("party_id IS NOT NULL"),
        ),
    )

    journal_entry_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    debit: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    credit: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    debit_base: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    credit_base: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    currency_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    exchange_rate: Mapped[Decimal] = mapped_column(_RATE, nullable=False, server_default=text("1"))
    party_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    party_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    external_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tax_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("taxes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    branch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    journal_entry: Mapped[JournalEntry] = relationship(back_populates="lines")
