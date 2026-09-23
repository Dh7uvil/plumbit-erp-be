"""Bank statement and reconciliation ORM."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Date,
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


class BankStatement(AuditUserMixin, SoftDeleteTenantModel):
    """Imported bank statement for a period."""

    __tablename__ = "bank_statements"
    __table_args__ = (
        Index("ix_bank_statements_tenant_id_bank_account_id", "tenant_id", "bank_account_id"),
        Index("ix_bank_statements_tenant_id_status", "tenant_id", "status"),
    )

    bank_account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("bank_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    closing_balance: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    base_opening_balance: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    base_closing_balance: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    import_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

    lines: Mapped[list["BankStatementLine"]] = relationship(
        back_populates="statement",
        cascade="all, delete-orphan",
        order_by="BankStatementLine.line_number",
    )


class BankStatementLine(TenantModel):
    """One imported statement row."""

    __tablename__ = "bank_statement_lines"
    __table_args__ = (
        UniqueConstraint("bank_statement_id", "line_number", name="uq_bank_statement_lines_line"),
        Index("ix_bank_statement_lines_statement_id", "bank_statement_id"),
        Index("ix_bank_statement_lines_match_status", "tenant_id", "match_status"),
    )

    bank_statement_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("bank_statements.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    line_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    debit: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    credit: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    match_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'UNMATCHED'")
    )
    matched_journal_line_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("journal_entry_lines.id", ondelete="SET NULL"),
        nullable=True,
    )

    statement: Mapped[BankStatement] = relationship(back_populates="lines")
