"""Warehouse schemas."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.schemas import AddressPayload, AddressResponse
from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_required_text


class WarehouseFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "code", "name"}
    )
    is_active: bool | None = None
    is_default: bool | None = None


class WarehouseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    address: AddressPayload | None = None
    is_default: bool = False

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return normalize_required_text(value, field_name="code").upper()

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WarehouseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    address: AddressPayload | None = None
    is_default: bool | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WarehouseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    code: str
    name: str
    phone: str | None
    address: AddressResponse | None = None
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
