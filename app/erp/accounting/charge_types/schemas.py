"""Charge type request/response schemas."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import ChargeAppliesTo, LandedCostAllocationMethod


class ChargeTypeFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "code", "sort_order", "is_active"}
    )
    is_active: bool | None = None
    applies_to: ChargeAppliesTo | None = None


class ChargeTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=150)
    sort_order: int = Field(default=0, ge=0)
    is_inventoriable: bool
    default_account_id: UUID
    allocation_basis: LandedCostAllocationMethod | None = None
    default_tax_id: UUID | None = None
    applies_to: ChargeAppliesTo = ChargeAppliesTo.BOTH

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip().upper().replace(" ", "_")
        if not normalized:
            raise ValueError("code is required")
        return normalized


class ChargeTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    sort_order: int | None = Field(default=None, ge=0)
    is_inventoriable: bool | None = None
    default_account_id: UUID | None = None
    allocation_basis: LandedCostAllocationMethod | None = None
    default_tax_id: UUID | None = None
    applies_to: ChargeAppliesTo | None = None
    is_active: bool | None = None


class ChargeTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    code: str
    name: str
    sort_order: int
    is_inventoriable: bool
    default_account_id: UUID
    allocation_basis: LandedCostAllocationMethod | None
    default_tax_id: UUID | None
    applies_to: ChargeAppliesTo
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None
