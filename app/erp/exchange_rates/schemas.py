"""Currency and exchange-rate request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_currency_code, normalize_required_text


class CurrencyFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "code", "name"}
    )
    is_base: bool | None = None
    is_active: bool | None = None


class CurrencyCreate(BaseModel):
    code: str = Field(min_length=3, max_length=3)
    name: str = Field(min_length=1, max_length=100)
    symbol: str = Field(min_length=1, max_length=10)
    decimal_places: int = Field(default=2, ge=0, le=6)
    is_base: bool = False

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return normalize_currency_code(value)

    @field_validator("name", "symbol")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return normalize_required_text(value, field_name="value")


class CurrencyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    symbol: str | None = Field(default=None, min_length=1, max_length=10)
    decimal_places: int | None = Field(default=None, ge=0, le=6)
    is_base: bool | None = None
    is_active: bool | None = None

    @field_validator("name", "symbol")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="value")


class CurrencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    code: str
    name: str
    symbol: str
    decimal_places: int
    is_base: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ExchangeRateUpsert(BaseModel):
    currency_id: UUID
    rate_to_base: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    effective_date: date | None = None


class ExchangeRateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    from_currency_id: UUID
    to_currency_id: UUID
    effective_date: date
    rate: Decimal
    created_at: datetime
    updated_at: datetime


class ExchangeRateResolveResponse(BaseModel):
    from_currency_id: UUID
    to_currency_id: UUID
    effective_date: date
    rate: Decimal
