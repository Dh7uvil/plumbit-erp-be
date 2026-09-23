"""Budget request and response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_required_text
from app.core.enums import BudgetStatus


class BudgetFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "fiscal_year", "status"}
    )
    status: BudgetStatus | None = None
    fiscal_year: int | None = None


class BudgetLineInput(BaseModel):
    account_id: UUID
    period_start: date
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    cost_center_id: UUID | None = None
    branch_id: UUID | None = None


class BudgetLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    period_start: date
    amount: Decimal
    cost_center_id: UUID | None
    branch_id: UUID | None


class BudgetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    fiscal_year: int = Field(ge=2000, le=2100)
    notes: str | None = None
    lines: list[BudgetLineInput] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")


class BudgetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    notes: str | None = None
    lines: list[BudgetLineInput] | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")


class BudgetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    fiscal_year: int
    status: BudgetStatus
    version: int
    notes: str | None
    lines: list[BudgetLineResponse] = Field(default_factory=list)
    available_actions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None


class BudgetVsActualLine(BaseModel):
    account_id: UUID
    account_code: str
    account_name: str
    account_type: str
    period_start: date
    cost_center_id: UUID | None = None
    branch_id: UUID | None = None
    budget_amount: Decimal
    actual_amount: Decimal
    variance_amount: Decimal
    source_type: str = "account"
    source_id: UUID | None = None


class BudgetVsActualResponse(BaseModel):
    budget_id: UUID
    budget_name: str
    currency_code: str
    from_date: date
    to_date: date
    total_budget: Decimal
    total_actual: Decimal
    total_variance: Decimal
    lines: list[BudgetVsActualLine] = Field(default_factory=list)
