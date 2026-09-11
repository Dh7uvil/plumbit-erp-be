"""Sales invoice request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.conversion import ConversionLineInput
from app.common.schemas.filters import BaseFilter
from app.common.schemas.packing import PackingFields
from app.common.schemas.related_documents import RelatedDocumentRef
from app.common.schemas.warnings import DocumentWarning
from app.core.enums import (
    CogsStatus,
    DiscountType,
    InvoiceDocumentStatus,
    PaymentStatus,
    PlaceOfSupply,
    TaxTreatment,
)


class SalesInvoiceFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "document_number",
            "invoice_date",
            "status",
            "grand_total",
            "due_date",
            "payment_status",
        }
    )
    status: InvoiceDocumentStatus | None = None
    customer_id: UUID | None = None
    sales_order_id: UUID | None = None
    source_quotation_id: UUID | None = None
    source_proforma_invoice_id: UUID | None = None
    branch_id: UUID | None = None
    currency_id: UUID | None = None
    payment_status: PaymentStatus | None = None
    invoice_date_from: date | None = None
    invoice_date_to: date | None = None

    @model_validator(mode="after")
    def validate_invoice_date_range(self) -> "SalesInvoiceFilter":
        if (
            self.invoice_date_from is not None
            and self.invoice_date_to is not None
            and self.invoice_date_from > self.invoice_date_to
        ):
            raise ValueError("invoice_date_from must be before or equal to invoice_date_to")
        return self


class SalesInvoiceLineInput(PackingFields):
    product_id: UUID | None = None
    description: str | None = None
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_id: UUID | None = None
    rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    sales_order_line_id: UUID | None = None
    source_quotation_line_id: UUID | None = None
    source_proforma_invoice_line_id: UUID | None = None
    delivery_note_id: UUID | None = None
    delivery_note_line_id: UUID | None = None
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
    def require_product_or_description(self) -> "SalesInvoiceLineInput":
        if self.product_id is None and not self.description:
            raise ValueError("Each line requires a product_id or a description")
        return self

    @model_validator(mode="after")
    def require_delivery_note_pair(self) -> "SalesInvoiceLineInput":
        if (self.delivery_note_id is None) != (self.delivery_note_line_id is None):
            raise ValueError("delivery_note_id and delivery_note_line_id must be set together")
        return self


class SalesInvoiceLineResponse(PackingFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    product_id: UUID | None
    description: str
    quantity: Decimal
    unit_id: UUID | None
    rate: Decimal
    sales_order_line_id: UUID | None
    source_quotation_line_id: UUID | None = None
    source_proforma_invoice_line_id: UUID | None = None
    delivery_note_id: UUID | None
    delivery_note_line_id: UUID | None
    discount_type: DiscountType | None
    discount_value: Decimal | None
    discount_amount: Decimal
    tax_id: UUID | None
    tax_rate: Decimal
    tax_amount: Decimal
    amount: Decimal
    income_account_id: UUID | None
    cogs_amount: Decimal
    cogs_status: CogsStatus
    qty_credited: Decimal


class SalesInvoiceCreate(BaseModel):
    customer_id: UUID
    contact_id: UUID | None = None
    branch_id: UUID | None = None
    invoice_date: date | None = None
    salesperson_id: UUID | None = None
    sales_order_id: UUID | None = None
    source_quotation_id: UUID | None = None
    source_proforma_invoice_id: UUID | None = None
    payment_terms_id: UUID | None = None
    currency_id: UUID | None = None
    notes: str | None = None
    terms_and_conditions: str | None = None
    bl_number: str | None = Field(default=None, max_length=80)
    container_number: str | None = Field(default=None, max_length=80)
    terms_template_id: UUID | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    shipping_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    adjustment_amount: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=4)
    round_off_amount: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=4)
    place_of_supply: PlaceOfSupply | None = None
    lines: list[SalesInvoiceLineInput] = Field(min_length=1)

    @field_validator("notes", "terms_and_conditions")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SalesInvoiceUpdate(BaseModel):
    contact_id: UUID | None = None
    branch_id: UUID | None = None
    invoice_date: date | None = None
    salesperson_id: UUID | None = None
    sales_order_id: UUID | None = None
    payment_terms_id: UUID | None = None
    currency_id: UUID | None = None
    notes: str | None = None
    terms_and_conditions: str | None = None
    bl_number: str | None = Field(default=None, max_length=80)
    container_number: str | None = Field(default=None, max_length=80)
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    shipping_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    adjustment_amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)
    round_off_amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)
    place_of_supply: PlaceOfSupply | None = None
    lines: list[SalesInvoiceLineInput] | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator("notes", "terms_and_conditions")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SalesInvoiceCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SalesInvoiceCreateFromSalesOrder(BaseModel):
    sales_order_id: UUID
    invoice_date: date | None = None
    notes: str | None = None
    lines: list[ConversionLineInput] | None = None


class SalesInvoiceCreateFromDeliveryNotes(BaseModel):
    delivery_note_ids: list[UUID] = Field(min_length=1)
    invoice_date: date | None = None
    notes: str | None = None


class SalesInvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    display_number: str
    status: InvoiceDocumentStatus
    version: int
    is_posted: bool
    invoice_date: date
    document_date: date
    customer_id: UUID
    contact_id: UUID | None
    customer_trn: str | None
    branch_id: UUID | None
    salesperson_id: UUID | None
    sales_order_id: UUID | None
    source_quotation_id: UUID | None = None
    source_proforma_invoice_id: UUID | None = None
    payment_terms_id: UUID | None
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
    bill_to_snapshot: str | None
    ship_to_snapshot: str | None
    notes: str | None
    terms_and_conditions: str | None
    bl_number: str | None = None
    container_number: str | None = None
    amount_paid: Decimal
    amount_credited: Decimal
    balance_due: Decimal
    payment_status: PaymentStatus
    cogs_amount: Decimal
    cogs_status: CogsStatus
    journal_entry_id: UUID | None
    reversal_journal_entry_id: UUID | None
    export_evidence_ok: bool
    export_evidence_checked_at: datetime | None
    posted_at: datetime | None
    posted_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    is_overdue: bool = False
    is_partially_credited: bool = False
    is_fully_credited: bool = False
    available_actions: list[str] = Field(default_factory=list)
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    warnings: list[DocumentWarning] = Field(default_factory=list)
    lines: list[SalesInvoiceLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class SalesInvoiceMarginLine(BaseModel):
    line_id: UUID
    line_number: int
    revenue: Decimal
    cogs_amount: Decimal
    cogs_status: CogsStatus
    margin: Decimal


class SalesInvoiceMarginResponse(BaseModel):
    invoice_id: UUID
    revenue: Decimal
    cogs_amount: Decimal
    cogs_status: CogsStatus
    margin: Decimal
    margin_percent: Decimal | None
    lines: list[SalesInvoiceMarginLine] = Field(default_factory=list)
