"""Entry book request/response schemas."""

from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter, SortOrder
from app.core.enums import VoucherType


class EntryBookFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"name", "voucher_type", "series_prefix"}
    )
    sort_by: str = "voucher_type"
    sort_order: SortOrder = "asc"
    voucher_type: VoucherType | None = None
    is_active: bool | None = None


class EntryBookUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    series_prefix: str | None = Field(default=None, max_length=20)
    default_account_id: UUID | None = None
    is_active: bool | None = None

    @field_validator("name", "series_prefix")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class EntryBookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    voucher_type: VoucherType
    name: str
    series_prefix: str
    default_account_id: UUID | None
    is_active: bool
