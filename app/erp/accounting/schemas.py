"""Accounting master request/response schemas."""

from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_required_text
from app.core.enums import DocumentType, TaxCategory


class TaxFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "rate"}
    )
    tax_category: TaxCategory | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class TaxCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    tax_category: TaxCategory
    rate: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")


class TaxUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    tax_category: TaxCategory | None = None
    rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    is_default: bool | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")


class TaxResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    tax_category: TaxCategory
    rate: Decimal
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PaymentTermFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "days"}
    )
    is_active: bool | None = None


class PaymentTermCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    days: int = Field(ge=0, le=3650)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")


class PaymentTermUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    days: int | None = Field(default=None, ge=0, le=3650)
    description: str | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")


class PaymentTermResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    days: int
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TermsTemplateFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "name"})
    is_default: bool | None = None
    is_active: bool | None = None


class TermsTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1)
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")


class TermsTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    body: str | None = Field(default=None, min_length=1)
    is_default: bool | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")


class TermsTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    body: str
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DocumentSequenceFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "document_type", "series", "fiscal_year"}
    )
    document_type: DocumentType | None = None
    series: str | None = None
    fiscal_year: int | None = None
    is_active: bool | None = None


class DocumentSequenceCreate(BaseModel):
    document_type: DocumentType
    series: str = Field(min_length=1, max_length=20)
    fiscal_year: int = Field(ge=2000, le=2100)
    prefix: str = Field(min_length=1, max_length=20)
    next_number: int = Field(default=1, ge=1)
    padding: int = Field(default=6, ge=1, le=10)

    @field_validator("series", "prefix")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return normalize_required_text(value, field_name="value").upper()


class DocumentSequenceUpdate(BaseModel):
    prefix: str | None = Field(default=None, min_length=1, max_length=20)
    next_number: int | None = Field(default=None, ge=1)
    padding: int | None = Field(default=None, ge=1, le=10)
    is_active: bool | None = None

    @field_validator("prefix")
    @classmethod
    def normalize_prefix(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="prefix").upper()


class DocumentSequenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_type: DocumentType
    series: str
    fiscal_year: int
    prefix: str
    next_number: int
    padding: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
