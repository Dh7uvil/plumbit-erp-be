"""Budget ORM models."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MONEY_PRECISION, MONEY_SCALE
from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin

_MONEY = Numeric(MONEY_PRECISION, MONEY_SCALE)


class Budget(AuditUserMixin, SoftDeleteTenantModel):
    """Named budget for one fiscal year. Amounts are plans, not ledger postings."""

    __tablename__ = "budgets"
    __table_args__ = (
        Index("ix_budgets_tenant_id_status", "tenant_id", "status"),
        Index("ix_budgets_tenant_id_fiscal_year", "tenant_id", "fiscal_year"),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class BudgetLine(TenantModel):
    """Monthly budget amount for an account, optionally by cost center or branch."""

    __tablename__ = "budget_lines"
    __table_args__ = (Index("ix_budget_lines_tenant_id_budget_id", "tenant_id", "budget_id"),)

    budget_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    cost_center_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cost_centers.id", ondelete="RESTRICT"),
        nullable=True,
    )
    branch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=True,
    )
