"""Financial category schemas."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_required_text
from app.core.enums import AccountSubtype, AccountType


class FinancialCategoryFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "account_type"}
    )
    account_type: AccountType | None = None


class FinancialCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    account_type: AccountType
    account_subtype: AccountSubtype | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")


class FinancialCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    account_type: AccountType | None = None
    account_subtype: AccountSubtype | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")


class FinancialCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    account_type: AccountType
    account_subtype: AccountSubtype | None = None
    created_at: datetime
    updated_at: datetime
