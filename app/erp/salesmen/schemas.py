"""Salesman targets schemas."""

from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.schemas.filters import BaseFilter


class SalesmanFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"employee_code"})


class SalesmanPeriodAmount(BaseModel):
    period: int = Field(ge=1, le=12)
    target: Decimal = Decimal("0")
    actual: Decimal = Decimal("0")


class SalesmanOverviewRow(BaseModel):
    employee_id: UUID
    employee_code: str
    name: str
    designation: str | None = None
    fiscal_year: int
    periods: list[SalesmanPeriodAmount]
    target_total: Decimal
    actual_total: Decimal


class SalesmanTargetsUpdate(BaseModel):
    fiscal_year: int
    periods: list[SalesmanPeriodAmount] = Field(min_length=1)
