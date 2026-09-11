"""Proforma invoice request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.conversion import ConversionLineInput
from app.common.schemas.filters import BaseFilter
from app.common.schemas.related_documents import RelatedDocumentRef
from app.core.enums import (
    DiscountType,
    Incoterm,
    PaymentMilestoneTrigger,
    PlaceOfSupply,
    ProformaInvoiceStatus,
    TaxTreatment,
)


class ProformaInvoiceFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "document_number",
            "proforma_date",
            "status",
            "grand_total",
        }
    )
    status: ProformaInvoiceStatus | None = None
    customer_id: UUID | None = None
    branch_id: UUID | None = None
    currency_id: UUID | None = None
    source_quotation_id: UUID | None = None
    source_sales_order_id: UUID | None = None


class ProformaInvoiceLineInput(BaseModel):
    product_id: UUID | None = None
    description: str | None = None
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_id: UUID | None = None
    rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax_id: UUID | None = None
    hs_code: str | None = Field(default=None, max_length=20)
    source_quotation_line_id: UUID | None = None
    source_sales_order_line_id: UUID | None = None

    @field_validator("description", "hs_code")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_product_or_description(self) -> "ProformaInvoiceLineInput":
        if self.product_id is None and not self.description:
            raise ValueError("Each line requires a product_id or a description")
        return self


class ProformaInvoiceLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    product_id: UUID | None
    description: str
    quantity: Decimal
    unit_id: UUID | None
    rate: Decimal
    discount_type: DiscountType | None
    discount_value: Decimal | None
    discount_amount: Decimal
    tax_id: UUID | None
    tax_rate: Decimal
    tax_amount: Decimal
    amount: Decimal
    hs_code: str | None
    source_quotation_line_id: UUID | None
    source_sales_order_line_id: UUID | None = None
    qty_converted: Decimal = Decimal("0")
    qty_remaining: Decimal = Decimal("0")

    @model_validator(mode="after")
    def compute_remaining(self) -> "ProformaInvoiceLineResponse":
        leftover = self.quantity - self.qty_converted
        self.qty_remaining = leftover if leftover > 0 else Decimal("0")
        return self


class ProformaInvoiceMilestoneInput(BaseModel):
    sequence: int | None = Field(default=None, ge=1)
    label: str = Field(min_length=1, max_length=120)
    trigger: PaymentMilestoneTrigger
    percent: Decimal | None = Field(default=None, ge=0, max_digits=9, decimal_places=4)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    net_days: int | None = Field(default=None, ge=0)
    due_date: date | None = None
    notes: str | None = None

    @field_validator("label", "notes")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProformaInvoiceMilestoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sequence: int
    label: str
    trigger: PaymentMilestoneTrigger
    percent: Decimal | None
    amount: Decimal | None
    net_days: int | None
    due_date: date | None
    computed_amount: Decimal
    notes: str | None


class ProformaInvoiceCreate(BaseModel):
    customer_id: UUID
    contact_id: UUID | None = None
    branch_id: UUID | None = None
    proforma_date: date | None = None
    valid_until: date | None = None
    currency_id: UUID | None = None
    price_list_id: UUID | None = None
    payment_terms_id: UUID | None = None
    salesperson_id: UUID | None = None
    notes: str | None = None
    terms_and_conditions: str | None = None
    terms_template_id: UUID | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    shipping_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    adjustment_amount: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=4)
    place_of_supply: PlaceOfSupply | None = None
    source_quotation_id: UUID | None = None
    source_sales_order_id: UUID | None = None
    incoterm: Incoterm | None = None
    incoterm_place: str | None = Field(default=None, max_length=120)
    port_of_loading: str | None = Field(default=None, max_length=120)
    port_of_discharge: str | None = Field(default=None, max_length=120)
    country_of_origin: str | None = Field(default=None, max_length=2)
    country_of_final_destination: str | None = Field(default=None, max_length=2)
    expected_shipment_date: date | None = None
    partial_shipment_allowed: bool = False
    transhipment_allowed: bool = False
    bank_details_snapshot: str | None = None
    lines: list[ProformaInvoiceLineInput] = Field(default_factory=list)
    milestones: list[ProformaInvoiceMilestoneInput] = Field(default_factory=list)

    @field_validator(
        "incoterm_place",
        "port_of_loading",
        "port_of_discharge",
        "country_of_origin",
        "country_of_final_destination",
        "bank_details_snapshot",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("country_of_origin", "country_of_final_destination")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.upper()


class ProformaInvoiceUpdate(BaseModel):
    contact_id: UUID | None = None
    branch_id: UUID | None = None
    proforma_date: date | None = None
    valid_until: date | None = None
    currency_id: UUID | None = None
    price_list_id: UUID | None = None
    payment_terms_id: UUID | None = None
    salesperson_id: UUID | None = None
    notes: str | None = None
    terms_and_conditions: str | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    shipping_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    adjustment_amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)
    place_of_supply: PlaceOfSupply | None = None
    incoterm: Incoterm | None = None
    incoterm_place: str | None = Field(default=None, max_length=120)
    port_of_loading: str | None = Field(default=None, max_length=120)
    port_of_discharge: str | None = Field(default=None, max_length=120)
    country_of_origin: str | None = Field(default=None, max_length=2)
    country_of_final_destination: str | None = Field(default=None, max_length=2)
    expected_shipment_date: date | None = None
    partial_shipment_allowed: bool | None = None
    transhipment_allowed: bool | None = None
    bank_details_snapshot: str | None = None
    lines: list[ProformaInvoiceLineInput] | None = None
    milestones: list[ProformaInvoiceMilestoneInput] | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator(
        "incoterm_place",
        "port_of_loading",
        "port_of_discharge",
        "country_of_origin",
        "country_of_final_destination",
        "bank_details_snapshot",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("country_of_origin", "country_of_final_destination")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.upper()


class ProformaInvoiceReasonRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ConvertProformaToSalesOrderRequest(BaseModel):
    order_date: date | None = None
    expected_shipment_date: date | None = None
    customer_po_number: str | None = Field(default=None, max_length=60)
    customer_po_date: date | None = None
    warehouse_id: UUID | None = None
    branch_id: UUID | None = None
    version: int | None = Field(default=None, ge=1)
    lines: list[ConversionLineInput] | None = None

    @field_validator("customer_po_number")
    @classmethod
    def normalize_po(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ConvertProformaToSalesInvoiceRequest(BaseModel):
    invoice_date: date | None = None
    notes: str | None = None
    version: int | None = Field(default=None, ge=1)
    lines: list[ConversionLineInput] | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProformaInvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    display_number: str
    status: ProformaInvoiceStatus
    version: int
    is_posted: bool
    proforma_date: date
    document_date: date
    valid_until: date | None
    branch_id: UUID | None
    customer_id: UUID
    contact_id: UUID | None
    customer_trn: str | None
    tax_treatment: TaxTreatment
    place_of_supply: PlaceOfSupply
    currency_id: UUID
    base_currency_id: UUID
    exchange_rate: Decimal
    price_list_id: UUID | None
    payment_terms_id: UUID | None
    salesperson_id: UUID | None
    notes: str | None
    terms_and_conditions: str | None
    bill_to_snapshot: str | None
    ship_to_snapshot: str | None
    discount_type: DiscountType | None
    discount_value: Decimal | None
    discount_amount: Decimal
    shipping_amount: Decimal
    adjustment_amount: Decimal
    subtotal: Decimal
    tax_amount: Decimal
    grand_total: Decimal
    foreign_amount: Decimal
    base_amount: Decimal
    source_quotation_id: UUID | None
    source_sales_order_id: UUID | None = None
    incoterm: Incoterm | None
    incoterm_place: str | None
    port_of_loading: str | None
    port_of_discharge: str | None
    country_of_origin: str | None
    country_of_final_destination: str | None
    expected_shipment_date: date | None
    partial_shipment_allowed: bool
    transhipment_allowed: bool
    bank_details_snapshot: str | None
    sent_at: datetime | None
    sent_by: UUID | None
    confirmed_at: datetime | None
    confirmed_by: UUID | None
    declined_at: datetime | None
    declined_by: UUID | None
    decline_reason: str | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    converted_at: datetime | None
    converted_document_type: str | None
    converted_document_id: UUID | None
    advance_required_amount: Decimal
    advance_outstanding: Decimal = Decimal("0")
    available_actions: list[str] = Field(default_factory=list)
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    lines: list[ProformaInvoiceLineResponse] = Field(default_factory=list)
    milestones: list[ProformaInvoiceMilestoneResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ProformaInvoiceComposeDefaults(BaseModel):
    customer_id: UUID
    customer_name: str
    customer_trn: str | None
    tax_treatment: TaxTreatment
    currency_id: UUID
    price_list_id: UUID | None
    payment_terms_id: UUID | None
    salesperson_id: UUID | None
    contact_id: UUID | None
    place_of_supply: PlaceOfSupply
    bill_to_snapshot: str | None
    ship_to_snapshot: str | None
    terms_and_conditions: str | None
