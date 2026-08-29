"""Product schemas."""

from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_required_text
from app.core.enums import ItemType


class ProductFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "sku", "name"}
    )
    item_type: ItemType | None = None
    category_id: UUID | None = None
    unit_id: UUID | None = None
    tax_id: UUID | None = None
    is_active: bool | None = None


class ProductCreate(BaseModel):
    item_type: ItemType = ItemType.PRODUCT
    sku: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    sales_description: str | None = None
    unit_id: UUID | None = None
    category_id: UUID | None = None
    selling_rate: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    tax_id: UUID | None = None
    hs_code: str | None = Field(default=None, max_length=20)
    track_inventory: bool = False

    @field_validator("sku")
    @classmethod
    def normalize_sku(cls, value: str) -> str:
        return normalize_required_text(value, field_name="sku").upper()

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("hs_code")
    @classmethod
    def normalize_hs(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProductUpdate(BaseModel):
    item_type: ItemType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sales_description: str | None = None
    unit_id: UUID | None = None
    category_id: UUID | None = None
    selling_rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax_id: UUID | None = None
    hs_code: str | None = Field(default=None, max_length=20)
    track_inventory: bool | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("hs_code")
    @classmethod
    def normalize_hs(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    item_type: ItemType
    sku: str
    name: str
    sales_description: str | None
    unit_id: UUID | None
    category_id: UUID | None
    selling_rate: Decimal
    tax_id: UUID | None
    hs_code: str | None
    track_inventory: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
