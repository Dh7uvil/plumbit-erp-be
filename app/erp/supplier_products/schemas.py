"""Supplier product catalog schemas."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import blank_to_none, normalize_required_text


class SupplierSkuResolveStatus(StrEnum):
    MAPPED = "MAPPED"
    UNMAPPED = "UNMAPPED"
    UNKNOWN_SKU = "UNKNOWN_SKU"


class SupplierProductFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"supplier_sku", "supplier_item_name", "created_at", "updated_at"}
    )
    supplier_id: UUID | None = None
    product_id: UUID | None = None
    mapped: bool | None = None
    is_active: bool | None = None
    is_preferred: bool | None = None
    is_preferred_supplier: bool | None = None
    q: str | None = None

    @field_validator("q")
    @classmethod
    def normalize_q(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def alias_q_to_search(self) -> "SupplierProductFilter":
        if self.search is None and self.q is not None:
            self.search = self.q
        return self


class SupplierProductCreate(BaseModel):
    supplier_id: UUID
    product_id: UUID | None = None
    supplier_sku: str = Field(min_length=1, max_length=80)
    supplier_item_name: str = Field(min_length=1, max_length=200)
    supplier_description: str | None = None
    price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    currency_id: UUID | None = None
    is_preferred: bool = False
    is_preferred_supplier: bool = False
    notes: str | None = None
    is_active: bool = True

    @field_validator("supplier_sku")
    @classmethod
    def normalize_sku(cls, value: str) -> str:
        return normalize_required_text(value, field_name="supplier_sku")

    @field_validator("supplier_item_name")
    @classmethod
    def normalize_item_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="supplier_item_name")

    @field_validator("supplier_description", "notes", mode="before")
    @classmethod
    def empty_optional_text(cls, value: object) -> object:
        return blank_to_none(value)


class SupplierProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_sku: str | None = Field(default=None, min_length=1, max_length=80)
    supplier_item_name: str | None = Field(default=None, min_length=1, max_length=200)
    supplier_description: str | None = None
    price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    currency_id: UUID | None = None
    is_preferred: bool | None = None
    is_preferred_supplier: bool | None = None
    notes: str | None = None
    is_active: bool | None = None

    @field_validator("supplier_sku")
    @classmethod
    def normalize_sku(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="supplier_sku")

    @field_validator("supplier_item_name")
    @classmethod
    def normalize_item_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="supplier_item_name")

    @field_validator("supplier_description", "notes", mode="before")
    @classmethod
    def empty_optional_text(cls, value: object) -> object:
        return blank_to_none(value)


class SupplierProductLinkRequest(BaseModel):
    product_id: UUID


class SupplierProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    supplier_id: UUID
    supplier_name: str | None
    product_id: UUID | None
    product_sku: str | None
    product_name: str | None
    is_mapped: bool
    supplier_sku: str
    supplier_item_name: str
    supplier_description: str | None
    price: Decimal | None
    currency_id: UUID
    currency_code: str | None
    price_updated_at: datetime | None
    is_preferred: bool
    is_preferred_supplier: bool
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SupplierProductResolveResponse(BaseModel):
    supplier_sku: str
    status: SupplierSkuResolveStatus
    supplier_product_id: UUID | None = None
    product_id: UUID | None = None
    product_sku: str | None = None
    product_name: str | None = None


class SupplierProductResolveBatchRequest(BaseModel):
    supplier_id: UUID
    supplier_skus: list[str] = Field(min_length=1, max_length=200)

    @field_validator("supplier_skus")
    @classmethod
    def require_skus(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("supplier_skus must not be empty")
        return value
