"""FX revaluation run ORM models."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MONEY_PRECISION, MONEY_SCALE
from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin

_MONEY = Numeric(MONEY_PRECISION, MONEY_SCALE)
_RATE = Numeric(18, 6)


class FxRevaluationRun(AuditUserMixin, SoftDeleteTenantModel):
    """One posted unrealized FX adjustment, reversible by a later journal."""

    __tablename__ = "fx_revaluation_runs"
    __table_args__ = (
        Index("ix_fx_revaluation_runs_tenant_id_status", "tenant_id", "status"),
        Index(
            "uq_fx_revaluation_runs_open",
            "tenant_id",
            unique=True,
            postgresql_where=text("status = 'POSTED' AND deleted_at IS NULL"),
        ),
    )

    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    journal_entry_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reversal_journal_entry_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_gain_base: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )


class FxRevaluationLine(TenantModel):
    """One revalued AR, AP, or bank bucket on a run."""

    __tablename__ = "fx_revaluation_lines"
    __table_args__ = (Index("ix_fx_revaluation_lines_run", "tenant_id", "run_id"),)

    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("fx_revaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    exposure_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    currency_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    party_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    party_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    foreign_balance: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    closing_rate: Mapped[Decimal] = mapped_column(_RATE, nullable=False)
    book_base: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    revalued_base: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    gain_base: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
