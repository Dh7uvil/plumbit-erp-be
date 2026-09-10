"""Credit note request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import (
    CreditNoteReason,
    DiscountType,
    InvoiceDocumentStatus,
    PlaceOfSupply,
    TaxTreatment,
)


class CreditNoteFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "document_number",
            "credit_note_date",
            "status",
            "grand_total",
        }
    )
    status: InvoiceDocumentStatus | None = None
    customer_id: UUID | None = None
    sales_invoice_id: UUID | None = None
    sales_return_id: UUID | None = None
    currency_id: UUID | None = None
    credit_note_date_from: date | None = None
    credit_note_date_to: date | None = None

    @model_validator(mode="after")
    def validate_credit_note_date_range(self) -> "CreditNoteFilter":
        if (
            self.credit_note_date_from is not None
            and self.credit_note_date_to is not None
            and self.credit_note_date_from > self.credit_note_date_to
        ):
            raise ValueError("credit_note_date_from must be before or equal to credit_note_date_to")
        return self


class CreditNoteLineInput(BaseModel):
    product_id: UUID | None = None
    description: str | None = None
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_id: UUID | None = None
    rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    sales_invoice_line_id: UUID | None = None
    sales_return_line_id: UUID | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax_id: UUID | None = None
    income_account_id: UUID | None = None

    @field_validator("description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_product_or_description(self) -> "CreditNoteLineInput":
        if self.product_id is None and not self.description:
            raise ValueError("Each line requires a product_id or a description")
        return self


class CreditNoteLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    product_id: UUID | None
    description: str
    quantity: Decimal
    unit_id: UUID | None
    rate: Decimal
    sales_invoice_line_id: UUID | None
    sales_return_line_id: UUID | None
    discount_type: DiscountType | None
    discount_value: Decimal | None
    discount_amount: Decimal
    tax_id: UUID | None
    tax_rate: Decimal
    tax_amount: Decimal
    amount: Decimal
    income_account_id: UUID | None


class CreditNoteCreate(BaseModel):
    customer_id: UUID
    sales_invoice_id: UUID | None = None
    sales_return_id: UUID | None = None
    reason_code: CreditNoteReason
    branch_id: UUID | None = None
    credit_note_date: date | None = None
    currency_id: UUID | None = None
    notes: str | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    shipping_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    adjustment_amount: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=4)
    round_off_amount: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=4)
    place_of_supply: PlaceOfSupply | None = None
    lines: list[CreditNoteLineInput] = Field(min_length=1)

    @field_validator("notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CreditNoteUpdate(BaseModel):
    sales_invoice_id: UUID | None = None
    sales_return_id: UUID | None = None
    reason_code: CreditNoteReason | None = None
    branch_id: UUID | None = None
    credit_note_date: date | None = None
    currency_id: UUID | None = None
    notes: str | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    shipping_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    adjustment_amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)
    round_off_amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)
    place_of_supply: PlaceOfSupply | None = None
    lines: list[CreditNoteLineInput] | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator("notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CreditNoteCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CreditNoteCreateFromSalesInvoice(BaseModel):
    sales_invoice_id: UUID
    credit_note_date: date | None = None
    reason_code: CreditNoteReason = CreditNoteReason.PRICE_ADJUSTMENT
    notes: str | None = None


class CreditNoteCreateFromSalesReturn(BaseModel):
    sales_return_id: UUID
    credit_note_date: date | None = None
    reason_code: CreditNoteReason = CreditNoteReason.GOODS_RETURNED
    notes: str | None = None


class CreditNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    display_number: str
    status: InvoiceDocumentStatus
    version: int
    is_posted: bool
    credit_note_date: date
    document_date: date
    customer_id: UUID
    sales_invoice_id: UUID | None
    sales_return_id: UUID | None
    reason_code: CreditNoteReason
    branch_id: UUID | None
    due_date: date | None
    tax_treatment: TaxTreatment
    place_of_supply: PlaceOfSupply
    is_export: bool
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
    lines: list[CreditNoteLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
