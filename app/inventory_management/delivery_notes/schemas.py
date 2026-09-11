"""Delivery note request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.schemas.related_documents import RelatedDocumentRef
from app.core.enums import PlaceOfSupply, StockDocumentStatus, TaxTreatment


class DeliveryNoteFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "document_number", "document_date", "status"}
    )
    status: StockDocumentStatus | None = None
    sales_order_id: UUID | None = None
    customer_id: UUID | None = None
    warehouse_id: UUID | None = None
    shipment_id: UUID | None = None
    unshipped: bool | None = None
    product_id: UUID | None = None
    document_date_from: date | None = None
    document_date_to: date | None = None

    @model_validator(mode="after")
    def validate_document_date_range(self) -> "DeliveryNoteFilter":
        if (
            self.document_date_from is not None
            and self.document_date_to is not None
            and self.document_date_from > self.document_date_to
        ):
            raise ValueError("document_date_from must be before or equal to document_date_to")
        return self


class DeliveryNoteLineInput(BaseModel):
    sales_order_line_id: UUID
    product_id: UUID | None = None
    description: str | None = None
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_id: UUID | None = None
    rate: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)

    @field_validator("description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DeliveryNoteLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    sales_order_line_id: UUID
    product_id: UUID | None
    description: str
    quantity: Decimal
    unit_id: UUID | None
    rate: Decimal
    qty_invoiced: Decimal = Decimal("0")


class DeliveryNoteCreate(BaseModel):
    sales_order_id: UUID
    warehouse_id: UUID | None = None
    document_date: date | None = None
    branch_id: UUID | None = None
    currency_id: UUID | None = None
    vehicle_number: str | None = Field(default=None, max_length=80)
    driver_name: str | None = Field(default=None, max_length=120)
    driver_contact: str | None = Field(default=None, max_length=40)
    notes: str | None = None
    lines: list[DeliveryNoteLineInput] = Field(min_length=1)

    @field_validator("vehicle_number", "driver_name", "driver_contact", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DeliveryNoteCreateFromSalesOrder(BaseModel):
    sales_order_id: UUID
    warehouse_id: UUID | None = None
    document_date: date | None = None
    notes: str | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DeliveryNoteUpdate(BaseModel):
    warehouse_id: UUID | None = None
    document_date: date | None = None
    branch_id: UUID | None = None
    currency_id: UUID | None = None
    vehicle_number: str | None = Field(default=None, max_length=80)
    driver_name: str | None = Field(default=None, max_length=120)
    driver_contact: str | None = Field(default=None, max_length=40)
    notes: str | None = None
    lines: list[DeliveryNoteLineInput] | None = Field(default=None, min_length=1)
    version: int | None = Field(default=None, ge=1)

    @field_validator("vehicle_number", "driver_name", "driver_contact", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DeliveryNoteCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DeliveryNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    status: StockDocumentStatus
    version: int
    is_posted: bool
    document_date: date
    sales_order_id: UUID
    customer_id: UUID
    warehouse_id: UUID
    branch_id: UUID | None
    shipment_id: UUID | None
    tax_treatment: TaxTreatment
    place_of_supply: PlaceOfSupply
    currency_id: UUID
    base_currency_id: UUID
    exchange_rate: Decimal
    vehicle_number: str | None
    driver_name: str | None
    driver_contact: str | None
    notes: str | None
    posted_at: datetime | None
    posted_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    available_actions: list[str] = Field(default_factory=list)
    period_locked: bool = False
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    lines: list[DeliveryNoteLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class DeliverableLineResponse(BaseModel):
    sales_order_line_id: UUID
    product_id: UUID | None
    description: str
    unit_id: UUID | None
    rate: Decimal
    quantity: Decimal
    qty_delivered: Decimal
    qty_returned: Decimal
    qty_reserved: Decimal
    outstanding: Decimal
