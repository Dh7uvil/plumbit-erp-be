"""Goods receipt request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.schemas.related_documents import RelatedDocumentRef
from app.core.enums import PlaceOfSupply, QcStatus, StockDocumentStatus, TaxTreatment


class GoodsReceiptFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "document_number", "document_date", "status"}
    )
    status: StockDocumentStatus | None = None
    warehouse_id: UUID | None = None
    supplier_id: UUID | None = None
    purchase_order_id: UUID | None = None
    qc_status: QcStatus | None = None
    product_id: UUID | None = None
    document_date_from: date | None = None
    document_date_to: date | None = None

    @model_validator(mode="after")
    def validate_document_date_range(self) -> "GoodsReceiptFilter":
        if (
            self.document_date_from is not None
            and self.document_date_to is not None
            and self.document_date_from > self.document_date_to
        ):
            raise ValueError("document_date_from must be before or equal to document_date_to")
        return self


class GoodsReceiptLineInput(BaseModel):
    purchase_order_line_id: UUID | None = None
    product_id: UUID | None = None
    supplier_product_id: UUID | None = None
    supplier_sku: str | None = Field(default=None, max_length=80)
    description: str | None = None
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_id: UUID | None = None
    rate: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    net_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    gross_weight: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)

    @field_validator("supplier_sku", "description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class GoodsReceiptLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    purchase_order_line_id: UUID | None
    product_id: UUID | None
    supplier_product_id: UUID | None
    supplier_sku: str | None
    description: str
    quantity: Decimal
    unit_id: UUID | None
    rate: Decimal
    net_weight: Decimal | None
    gross_weight: Decimal | None
    qty_accepted: Decimal
    qty_rejected: Decimal
    qty_on_hold: Decimal
    qty_billed: Decimal = Decimal("0")


class GoodsReceiptCreate(BaseModel):
    supplier_id: UUID
    warehouse_id: UUID
    document_date: date | None = None
    purchase_order_id: UUID | None = None
    branch_id: UUID | None = None
    currency_id: UUID | None = None
    supplier_invoice_number: str | None = Field(default=None, max_length=80)
    delivery_challan_number: str | None = Field(default=None, max_length=80)
    bill_of_entry_number: str | None = Field(default=None, max_length=80)
    bill_of_entry_date: date | None = None
    container_number: str | None = Field(default=None, max_length=80)
    bl_number: str | None = Field(default=None, max_length=80)
    notes: str | None = None
    lines: list[GoodsReceiptLineInput] = Field(min_length=1)

    @field_validator(
        "supplier_invoice_number",
        "delivery_challan_number",
        "bill_of_entry_number",
        "container_number",
        "bl_number",
        "notes",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class GoodsReceiptCreateFromPurchaseOrder(BaseModel):
    purchase_order_id: UUID
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


class GoodsReceiptUpdate(BaseModel):
    warehouse_id: UUID | None = None
    document_date: date | None = None
    branch_id: UUID | None = None
    currency_id: UUID | None = None
    supplier_invoice_number: str | None = Field(default=None, max_length=80)
    delivery_challan_number: str | None = Field(default=None, max_length=80)
    bill_of_entry_number: str | None = Field(default=None, max_length=80)
    bill_of_entry_date: date | None = None
    container_number: str | None = Field(default=None, max_length=80)
    bl_number: str | None = Field(default=None, max_length=80)
    notes: str | None = None
    lines: list[GoodsReceiptLineInput] | None = Field(default=None, min_length=1)
    version: int | None = Field(default=None, ge=1)

    @field_validator(
        "supplier_invoice_number",
        "delivery_challan_number",
        "bill_of_entry_number",
        "container_number",
        "bl_number",
        "notes",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class GoodsReceiptCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class GoodsReceiptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    status: StockDocumentStatus
    version: int
    is_posted: bool
    document_date: date
    supplier_id: UUID
    warehouse_id: UUID
    purchase_order_id: UUID | None
    branch_id: UUID | None
    tax_treatment: TaxTreatment
    place_of_supply: PlaceOfSupply
    currency_id: UUID
    base_currency_id: UUID
    exchange_rate: Decimal
    supplier_invoice_number: str | None
    delivery_challan_number: str | None
    bill_of_entry_number: str | None
    bill_of_entry_date: date | None
    container_number: str | None
    bl_number: str | None
    notes: str | None
    qc_status: QcStatus
    posted_at: datetime | None
    posted_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    available_actions: list[str] = Field(default_factory=list)
    period_locked: bool = False
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    lines: list[GoodsReceiptLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
