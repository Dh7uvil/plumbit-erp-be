"""Price-list schemas."""

from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_required_text
from app.core.enums import PriceListType


class PriceListFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "name"})
    currency_id: UUID | None = None
    list_type: PriceListType | None = None
    is_active: bool | None = None


class PriceListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    currency_id: UUID
    list_type: PriceListType
    percent: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @model_validator(mode="after")
    def validate_percent(self) -> "PriceListCreate":
        if self.list_type == PriceListType.PERCENT and self.percent is None:
            raise ValueError("percent is required for PERCENT price lists")
        return self


class PriceListUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    percent: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")


class PriceListItemUpsert(BaseModel):
    product_id: UUID
    rate: Decimal = Field(ge=0, max_digits=18, decimal_places=4)


class PriceListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    price_list_id: UUID
    product_id: UUID
    rate: Decimal


class PriceListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    currency_id: UUID
    list_type: PriceListType
    percent: Decimal | None
    is_active: bool
    items: list[PriceListItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
