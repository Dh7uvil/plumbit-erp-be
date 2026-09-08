"""Sales order request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import (
    BillingStatus,
    DiscountType,
    FulfillmentStatus,
    PlaceOfSupply,
    SalesOrderStatus,
    TaxTreatment,
)


class SalesOrderFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "document_number",
            "order_date",
            "status",
            "grand_total",
        }
    )
    status: SalesOrderStatus | None = None
    fulfillment_status: FulfillmentStatus | None = None
    billing_status: BillingStatus | None = None
    customer_id: UUID | None = None
    branch_id: UUID | None = None
    warehouse_id: UUID | None = None
    currency_id: UUID | None = None
    salesperson_id: UUID | None = None
    source_quotation_id: UUID | None = None


class SalesOrderLineInput(BaseModel):
    product_id: UUID | None = None
    description: str | None = None
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_id: UUID | None = None
    rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax_id: UUID | None = None

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_product_or_description(self) -> "SalesOrderLineInput":
        if self.product_id is None and not self.description:
            raise ValueError("Each line requires a product_id or a description")
        return self


class SalesOrderLineResponse(BaseModel):
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
    qty_delivered: Decimal
    qty_invoiced: Decimal
    source_quotation_line_id: UUID | None


class SalesOrderCreate(BaseModel):
    customer_id: UUID
    contact_id: UUID | None = None
    branch_id: UUID | None = None
    warehouse_id: UUID | None = None
    order_date: date | None = None
    expected_shipment_date: date | None = None
    reference_number: str | None = Field(default=None, max_length=60)
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
    lines: list[SalesOrderLineInput] = Field(default_factory=list)

    @field_validator("reference_number")
    @classmethod
    def normalize_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SalesOrderUpdate(BaseModel):
    contact_id: UUID | None = None
    branch_id: UUID | None = None
    warehouse_id: UUID | None = None
    order_date: date | None = None
    expected_shipment_date: date | None = None
    reference_number: str | None = Field(default=None, max_length=60)
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
    lines: list[SalesOrderLineInput] | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator("reference_number")
    @classmethod
    def normalize_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SalesOrderRejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SalesOrderCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SalesOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    status: SalesOrderStatus
    version: int
    is_posted: bool
    reference_number: str | None
    order_date: date
    document_date: date
    expected_shipment_date: date | None
    branch_id: UUID | None
    warehouse_id: UUID | None
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
    fulfillment_status: FulfillmentStatus
    billing_status: BillingStatus
    source_quotation_id: UUID | None
    confirmed_at: datetime | None
    confirmed_by: UUID | None
    closed_at: datetime | None
    closed_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    available_actions: list[str] = Field(default_factory=list)
    lines: list[SalesOrderLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class SalesOrderComposeDefaults(BaseModel):
    customer_id: UUID
    customer_name: str
    customer_trn: str | None
    tax_treatment: TaxTreatment
    currency_id: UUID
    price_list_id: UUID | None
    payment_terms_id: UUID | None
    salesperson_id: UUID | None
    contact_id: UUID | None
    warehouse_id: UUID | None
    place_of_supply: PlaceOfSupply
    bill_to_snapshot: str | None
    ship_to_snapshot: str | None
    terms_and_conditions: str | None
