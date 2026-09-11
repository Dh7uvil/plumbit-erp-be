"""Customer receipt request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.schemas.related_documents import RelatedDocumentRef
from app.core.enums import InvoiceDocumentStatus, PaymentMethod
from app.erp.accounting.open_items.schemas import PaymentAllocationInput


class CustomerPaymentFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "document_number",
            "payment_date",
            "status",
            "amount_received",
        }
    )
    status: InvoiceDocumentStatus | None = None
    customer_id: UUID | None = None
    proforma_invoice_id: UUID | None = None
    sales_order_id: UUID | None = None
    currency_id: UUID | None = None
    payment_method: PaymentMethod | None = None
    payment_date_from: date | None = None
    payment_date_to: date | None = None

    @model_validator(mode="after")
    def validate_payment_date_range(self) -> "CustomerPaymentFilter":
        if (
            self.payment_date_from is not None
            and self.payment_date_to is not None
            and self.payment_date_from > self.payment_date_to
        ):
            raise ValueError("payment_date_from must be before or equal to payment_date_to")
        return self


class CustomerPaymentAllocationResponse(BaseModel):
    item_type: str
    item_id: UUID
    amount: Decimal
    journal_entry_id: UUID | None = None


class CustomerPaymentCreate(BaseModel):
    customer_id: UUID
    payment_date: date | None = None
    currency_id: UUID | None = None
    amount_received: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    bank_charges: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    payment_account_id: UUID
    payment_method: PaymentMethod = PaymentMethod.BANK
    reference: str | None = Field(default=None, max_length=100)
    proforma_invoice_id: UUID | None = None
    sales_order_id: UUID | None = None
    tax_id: UUID | None = None
    notes: str | None = None
    allocations: list[PaymentAllocationInput] = Field(default_factory=list)

    @field_validator("reference", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CustomerPaymentUpdate(BaseModel):
    payment_date: date | None = None
    currency_id: UUID | None = None
    amount_received: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    bank_charges: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    payment_account_id: UUID | None = None
    payment_method: PaymentMethod | None = None
    reference: str | None = Field(default=None, max_length=100)
    proforma_invoice_id: UUID | None = None
    sales_order_id: UUID | None = None
    tax_id: UUID | None = None
    notes: str | None = None
    allocations: list[PaymentAllocationInput] | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator("reference", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CustomerPaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    display_number: str
    status: InvoiceDocumentStatus
    version: int
    is_posted: bool
    payment_date: date
    document_date: date
    customer_id: UUID
    currency_id: UUID
    base_currency_id: UUID
    exchange_rate: Decimal
    amount_received: Decimal
    bank_charges: Decimal
    amount_unapplied: Decimal
    amount_refunded: Decimal
    payment_account_id: UUID
    payment_method: PaymentMethod
    reference: str | None
    proforma_invoice_id: UUID | None
    sales_order_id: UUID | None
    journal_entry_id: UUID | None
    reversal_journal_entry_id: UUID | None
    refund_journal_entry_id: UUID | None
    tax_id: UUID | None
    tax_amount: Decimal
    notes: str | None
    posted_at: datetime | None
    posted_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    refunded_at: datetime | None
    refunded_by: UUID | None
    available_actions: list[str] = Field(default_factory=list)
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    allocations: list[CustomerPaymentAllocationResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
