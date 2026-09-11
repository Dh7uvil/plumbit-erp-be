"""Package request/response schemas."""

from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.common.schemas.related_documents import RelatedDocumentRef
from app.core.enums import PackageStatus


class PackageFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "document_number", "status"}
    )
    status: PackageStatus | None = None
    sales_order_id: UUID | None = None
    delivery_note_id: UUID | None = None


class PackageLineInput(BaseModel):
    sales_order_line_id: UUID
    product_id: UUID | None = None
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_id: UUID | None = None


class PackageLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    sales_order_line_id: UUID
    product_id: UUID | None
    quantity: Decimal
    unit_id: UUID | None


class PackageCreate(BaseModel):
    sales_order_id: UUID
    delivery_note_id: UUID | None = None
    package_number: str | None = Field(default=None, max_length=40)
    length: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    width: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    height: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    dimension_unit: str | None = Field(default=None, max_length=10)
    gross_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    net_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    weight_unit: str | None = Field(default=None, max_length=10)
    shipping_marks: str | None = None
    notes: str | None = None
    lines: list[PackageLineInput] = Field(min_length=1)

    @field_validator("package_number", "dimension_unit", "weight_unit", "shipping_marks", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PackageUpdate(BaseModel):
    delivery_note_id: UUID | None = None
    package_number: str | None = Field(default=None, max_length=40)
    length: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    width: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    height: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    dimension_unit: str | None = Field(default=None, max_length=10)
    gross_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    net_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    weight_unit: str | None = Field(default=None, max_length=10)
    shipping_marks: str | None = None
    notes: str | None = None
    lines: list[PackageLineInput] | None = Field(default=None, min_length=1)
    version: int | None = Field(default=None, ge=1)

    @field_validator("package_number", "dimension_unit", "weight_unit", "shipping_marks", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PackageAttachRequest(BaseModel):
    package_id: UUID


class PackageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    status: PackageStatus
    version: int
    sales_order_id: UUID
    delivery_note_id: UUID | None
    package_number: str | None
    length: Decimal | None
    width: Decimal | None
    height: Decimal | None
    dimension_unit: str | None
    gross_weight: Decimal | None
    net_weight: Decimal | None
    weight_unit: str | None
    shipping_marks: str | None
    notes: str | None
    available_actions: list[str] = Field(default_factory=list)
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    lines: list[PackageLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PackableLineResponse(BaseModel):
    sales_order_line_id: UUID
    product_id: UUID | None
    description: str
    unit_id: UUID | None
    quantity: Decimal
    qty_packed: Decimal
    outstanding: Decimal
