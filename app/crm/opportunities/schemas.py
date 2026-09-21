"""Opportunity request and response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import OpportunityStatus


class OpportunityFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "opportunity_number",
            "name",
            "status",
            "amount",
            "expected_close_date",
        }
    )
    status: OpportunityStatus | None = None
    pipeline_id: UUID | None = None
    stage_id: UUID | None = None
    owner_id: UUID | None = None
    customer_id: UUID | None = None
    source_id: UUID | None = None


class OpportunityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    customer_id: UUID | None = None
    contact_id: UUID | None = None
    pipeline_id: UUID | None = None
    stage_id: UUID | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    currency_id: UUID | None = None
    probability: Decimal | None = Field(default=None, ge=0, le=100)
    expected_close_date: date | None = None
    owner_id: UUID | None = None
    source_id: UUID | None = None
    lead_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @model_validator(mode="after")
    def amount_requires_currency(self) -> Self:
        if (self.amount is None) != (self.currency_id is None):
            raise ValueError("amount and currency_id must be provided together")
        return self


class OpportunityUpdate(BaseModel):
    version: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    customer_id: UUID | None = None
    contact_id: UUID | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    currency_id: UUID | None = None
    probability: Decimal | None = Field(default=None, ge=0, le=100)
    expected_close_date: date | None = None
    owner_id: UUID | None = None
    source_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


class OpportunityStageChange(BaseModel):
    stage_id: UUID
    lost_reason_id: UUID | None = None
    version: int | None = Field(default=None, ge=1)


class OpportunityLose(BaseModel):
    lost_reason_id: UUID
    version: int | None = Field(default=None, ge=1)


class OpportunityVersionedAction(BaseModel):
    version: int | None = Field(default=None, ge=1)


class OpportunityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    opportunity_number: str
    name: str
    customer_id: UUID | None
    contact_id: UUID | None
    pipeline_id: UUID
    stage_id: UUID
    amount: Decimal | None
    currency_id: UUID | None
    probability: Decimal | None
    expected_close_date: date | None
    status: OpportunityStatus
    lost_reason_id: UUID | None
    owner_id: UUID | None
    source_id: UUID | None
    lead_id: UUID | None
    version: int
    available_actions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None
