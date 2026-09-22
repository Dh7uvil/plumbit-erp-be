"""Bank account request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_required_text


class BankAccountFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "account_name", "bank_name", "is_active"}
    )
    is_active: bool | None = None
    currency_id: UUID | None = None


class BankAccountCreate(BaseModel):
    account_id: UUID
    account_name: str = Field(min_length=1, max_length=150)
    bank_name: str = Field(min_length=1, max_length=150)
    branch_name: str | None = Field(default=None, max_length=150)
    account_number: str | None = Field(default=None, max_length=50)
    iban: str | None = Field(default=None, max_length=50)
    swift: str | None = Field(default=None, max_length=20)
    currency_id: UUID
    opening_balance: Decimal = Field(default=Decimal("0"))
    opening_date: date | None = None
    is_default: bool = False

    @field_validator("account_name", "bank_name")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")


class BankAccountUpdate(BaseModel):
    account_name: str | None = Field(default=None, min_length=1, max_length=150)
    bank_name: str | None = Field(default=None, min_length=1, max_length=150)
    branch_name: str | None = Field(default=None, max_length=150)
    account_number: str | None = Field(default=None, max_length=50)
    iban: str | None = Field(default=None, max_length=50)
    swift: str | None = Field(default=None, max_length=20)
    currency_id: UUID | None = None
    opening_balance: Decimal | None = None
    opening_date: date | None = None
    is_default: bool | None = None
    is_active: bool | None = None

    @field_validator("account_name", "bank_name")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")


class BankAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    account_id: UUID
    account_name: str
    bank_name: str
    branch_name: str | None
    account_number: str | None
    iban: str | None
    swift: str | None
    currency_id: UUID
    opening_balance: Decimal
    opening_date: date | None
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None
