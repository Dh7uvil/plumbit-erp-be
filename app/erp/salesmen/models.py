"""Sales target ORM."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Numeric, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MONEY_PRECISION, MONEY_SCALE
from app.db.base import TenantModel

_MONEY = Numeric(MONEY_PRECISION, MONEY_SCALE)


class SalesTarget(TenantModel):
    __tablename__ = "sales_targets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "employee_id",
            "fiscal_year",
            "period",
            name="uq_sales_targets_employee_period",
        ),
    )

    employee_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
