"""Debit note request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.schemas.related_documents import RelatedDocumentRef
from app.core.enums import (
    DebitNoteReason,
    DiscountType,
    InvoiceDocumentStatus,
    PlaceOfSupply,
    TaxTreatment,
)


class DebitNoteFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "document_number",
            "debit_note_date",
            "status",
            "grand_total",
        }
    )
    status: InvoiceDocumentStatus | None = None
    supplier_id: UUID | None = None
    purchase_invoice_id: UUID | None = None
    purchase_return_id: UUID | None = None
    currency_id: UUID | None = None
    debit_note_date_from: date | None = None
    debit_note_date_to: date | None = None

    @model_validator(mode="after")
    def validate_debit_note_date_range(self) -> "DebitNoteFilter":
        if (
            self.debit_note_date_from is not None
            and self.debit_note_date_to is not None
            and self.debit_note_date_from > self.debit_note_date_to
        ):
            raise ValueError("debit_note_date_from must be before or equal to debit_note_date_to")
        return self


class DebitNoteLineInput(BaseModel):
    product_id: UUID | None = None
    description: str | None = None
    quantity: Decimal = Field(default=Decimal("1"), gt=0, max_digits=18, decimal_places=6)
    unit_id: UUID | None = None
    rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    purchase_invoice_line_id: UUID | None = None
    purchase_return_line_id: UUID | None = None
    expense_account_id: UUID | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax_id: UUID | None = None

    @field_validator("description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_product_or_description(self) -> "DebitNoteLineInput":
        if self.product_id is None and not self.description:
            raise ValueError("Each line requires a product_id or a description")
        return self


class DebitNoteLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    product_id: UUID | None
    description: str
    quantity: Decimal
    unit_id: UUID | None
    rate: Decimal
    purchase_invoice_line_id: UUID | None
    purchase_return_line_id: UUID | None = None
    expense_account_id: UUID | None
    discount_type: DiscountType | None
    discount_value: Decimal | None
    discount_amount: Decimal
    tax_id: UUID | None
    tax_rate: Decimal
    tax_amount: Decimal
    amount: Decimal


class DebitNoteCreate(BaseModel):
    purchase_invoice_id: UUID | None = None
    purchase_return_id: UUID | None = None
    supplier_id: UUID
    reason_code: DebitNoteReason
    branch_id: UUID | None = None
    debit_note_date: date | None = None
    currency_id: UUID | None = None
    notes: str | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    shipping_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    adjustment_amount: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=4)
    round_off_amount: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=4)
    place_of_supply: PlaceOfSupply | None = None
    lines: list[DebitNoteLineInput] = Field(min_length=1)

    @field_validator("notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DebitNoteUpdate(BaseModel):
    reason_code: DebitNoteReason | None = None
    branch_id: UUID | None = None
    debit_note_date: date | None = None
    currency_id: UUID | None = None
    notes: str | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    shipping_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    adjustment_amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)
    round_off_amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)
    place_of_supply: PlaceOfSupply | None = None
    lines: list[DebitNoteLineInput] | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator("notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DebitNoteCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DebitNoteCreateFromPurchaseInvoice(BaseModel):
    purchase_invoice_id: UUID
    debit_note_date: date | None = None
    reason_code: DebitNoteReason = DebitNoteReason.PRICE_ADJUSTMENT
    notes: str | None = None


class DebitNoteCreateFromPurchaseReturn(BaseModel):
    purchase_return_id: UUID
    debit_note_date: date | None = None
    reason_code: DebitNoteReason = DebitNoteReason.GOODS_REJECTED
    notes: str | None = None


class DebitNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    display_number: str
    status: InvoiceDocumentStatus
    version: int
    is_posted: bool
    debit_note_date: date
    document_date: date
    purchase_invoice_id: UUID | None
    purchase_return_id: UUID | None = None
    supplier_id: UUID
    reason_code: DebitNoteReason
    branch_id: UUID | None
    due_date: date | None
    tax_treatment: TaxTreatment
    place_of_supply: PlaceOfSupply
    currency_id: UUID
    base_currency_id: UUID
    exchange_rate: Decimal
    discount_type: DiscountType | None
    discount_value: Decimal | None
    discount_amount: Decimal
    shipping_amount: Decimal
    adjustment_amount: Decimal
    round_off_amount: Decimal
    subtotal: Decimal
    tax_amount: Decimal
    grand_total: Decimal
    foreign_amount: Decimal
    base_amount: Decimal
    notes: str | None
    amount_applied: Decimal
    amount_unapplied: Decimal
    journal_entry_id: UUID | None
    reversal_journal_entry_id: UUID | None
    posted_at: datetime | None
    posted_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    available_actions: list[str] = Field(default_factory=list)
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    lines: list[DebitNoteLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
