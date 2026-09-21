"""Campaign request and response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_required_text
from app.core.enums import CampaignMemberStatus, CampaignMemberType, CampaignStatus, CampaignType


class CampaignFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "name",
            "status",
            "campaign_type",
            "start_date",
            "end_date",
        }
    )
    status: CampaignStatus | None = None
    campaign_type: CampaignType | None = None
    owner_id: UUID | None = None


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    campaign_type: CampaignType
    status: CampaignStatus = CampaignStatus.PLANNED
    start_date: date | None = None
    end_date: date | None = None
    budgeted_cost: Decimal | None = Field(default=None, ge=0)
    actual_cost: Decimal | None = Field(default=None, ge=0)
    expected_revenue: Decimal | None = Field(default=None, ge=0)
    owner_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date must be on or after start_date")
        return self


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    campaign_type: CampaignType | None = None
    status: CampaignStatus | None = None
    start_date: date | None = None
    end_date: date | None = None
    budgeted_cost: Decimal | None = Field(default=None, ge=0)
    actual_cost: Decimal | None = Field(default=None, ge=0)
    expected_revenue: Decimal | None = Field(default=None, ge=0)
    owner_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date must be on or after start_date")
        return self


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    campaign_type: CampaignType
    status: CampaignStatus
    start_date: date | None
    end_date: date | None
    budgeted_cost: Decimal | None
    actual_cost: Decimal | None
    expected_revenue: Decimal | None
    owner_id: UUID | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None


class CampaignMemberCreate(BaseModel):
    member_type: CampaignMemberType
    member_id: UUID
    member_status: CampaignMemberStatus = CampaignMemberStatus.PLANNED


class CampaignMemberUpdate(BaseModel):
    member_status: CampaignMemberStatus


class CampaignMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    campaign_id: UUID
    member_type: CampaignMemberType
    member_id: UUID
    member_status: CampaignMemberStatus
    member_label: str | None = None
    created_at: datetime
    updated_at: datetime


class CampaignRoiResponse(BaseModel):
    campaign_id: UUID
    member_count: int
    converted_leads: int
    won_opportunity_count: int
    won_opportunity_value: Decimal
    budgeted_cost: Decimal | None
    actual_cost: Decimal | None
    expected_revenue: Decimal | None
    roi: Decimal | None
