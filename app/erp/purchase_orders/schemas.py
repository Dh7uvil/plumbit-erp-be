"""Purchase order request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import (
    BillingStatus,
    DiscountType,
    PlaceOfSupply,
    PurchaseOrderStatus,
    ReceiptStatus,
    TaxTreatment,
)


class PurchaseOrderFilter(BaseFilter):
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
    status: PurchaseOrderStatus | None = None
    receipt_status: ReceiptStatus | None = None
    billing_status: BillingStatus | None = None
    supplier_id: UUID | None = None
    branch_id: UUID | None = None
    warehouse_id: UUID | None = None
    currency_id: UUID | None = None
    source_sales_order_id: UUID | None = None


class PurchaseOrderLineInput(BaseModel):
    product_id: UUID | None = None
    supplier_product_id: UUID | None = None
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
    def require_product_or_description(self) -> "PurchaseOrderLineInput":
        if self.product_id is None and self.supplier_product_id is None and not self.description:
            raise ValueError(
                "Each line requires a product_id, supplier_product_id, or a description"
            )
        return self


class PurchaseOrderLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    product_id: UUID | None
    supplier_product_id: UUID | None = None
    supplier_sku: str | None = None
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
    qty_received: Decimal
    qty_billed: Decimal
    source_sales_order_line_id: UUID | None = None


class PurchaseOrderCreate(BaseModel):
    supplier_id: UUID
    contact_id: UUID | None = None
    branch_id: UUID | None = None
    warehouse_id: UUID | None = None
    order_date: date | None = None
    expected_delivery_date: date | None = None
    reference_number: str | None = Field(default=None, max_length=60)
    currency_id: UUID | None = None
    payment_terms_id: UUID | None = None
    notes: str | None = None
    terms_and_conditions: str | None = None
    terms_template_id: UUID | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    shipping_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    adjustment_amount: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=4)
    place_of_supply: PlaceOfSupply | None = None
    lines: list[PurchaseOrderLineInput] = Field(default_factory=list)

    @field_validator("reference_number")
    @classmethod
    def normalize_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PurchaseOrderUpdate(BaseModel):
    contact_id: UUID | None = None
    branch_id: UUID | None = None
    warehouse_id: UUID | None = None
    order_date: date | None = None
    expected_delivery_date: date | None = None
    reference_number: str | None = Field(default=None, max_length=60)
    currency_id: UUID | None = None
    payment_terms_id: UUID | None = None
    notes: str | None = None
    terms_and_conditions: str | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    shipping_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    adjustment_amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)
    place_of_supply: PlaceOfSupply | None = None
    lines: list[PurchaseOrderLineInput] | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator("reference_number")
    @classmethod
    def normalize_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PurchaseOrderRejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PurchaseOrderCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PurchaseOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    status: PurchaseOrderStatus
    version: int
    is_posted: bool
    reference_number: str | None
    order_date: date
    document_date: date
    expected_delivery_date: date | None
    branch_id: UUID | None
    warehouse_id: UUID | None
    supplier_id: UUID
    contact_id: UUID | None
    supplier_trn: str | None
    tax_treatment: TaxTreatment
    place_of_supply: PlaceOfSupply
    currency_id: UUID
    base_currency_id: UUID
    exchange_rate: Decimal
    payment_terms_id: UUID | None
    notes: str | None
    terms_and_conditions: str | None
    supplier_address_snapshot: str | None
    deliver_to_snapshot: str | None
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
    receipt_status: ReceiptStatus
    billing_status: BillingStatus
    issued_at: datetime | None
    issued_by: UUID | None
    closed_at: datetime | None
    closed_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    source_sales_order_id: UUID | None = None
    available_actions: list[str] = Field(default_factory=list)
    lines: list[PurchaseOrderLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PurchaseOrderComposeDefaults(BaseModel):
    supplier_id: UUID
    supplier_name: str
    supplier_trn: str | None
    tax_treatment: TaxTreatment
    currency_id: UUID
    payment_terms_id: UUID | None
    contact_id: UUID | None
    warehouse_id: UUID | None
    place_of_supply: PlaceOfSupply
    supplier_address_snapshot: str | None
    deliver_to_snapshot: str | None
    terms_and_conditions: str | None


class CoveragePurchaseOrderRef(BaseModel):
    id: UUID
    document_number: str
    status: PurchaseOrderStatus
    quantity: Decimal
    qty_received: Decimal


class SalesOrderCoverageLine(BaseModel):
    sales_order_line_id: UUID
    product_id: UUID | None
    description: str
    quantity: Decimal
    qty_covered: Decimal
    qty_uncovered: Decimal
    qty_received: Decimal
    qty_reserved: Decimal = Decimal("0")
    qty_delivered: Decimal = Decimal("0")
    qty_returned: Decimal = Decimal("0")
    purchase_orders: list[CoveragePurchaseOrderRef] = Field(default_factory=list)


class SalesOrderCoverageResponse(BaseModel):
    sales_order_id: UUID
    lines: list[SalesOrderCoverageLine] = Field(default_factory=list)


class PurchaseOrderPlanLine(BaseModel):
    sales_order_line_id: UUID
    product_id: UUID | None
    description: str
    qty_uncovered: Decimal
    supplier_product_id: UUID | None = None
    supplier_sku: str | None = None
    catalog_price: Decimal | None = None
    catalog_currency_id: UUID | None = None


class PurchaseOrderPlanGroup(BaseModel):
    supplier_id: UUID
    supplier_name: str
    currency_id: UUID
    lines: list[PurchaseOrderPlanLine] = Field(default_factory=list)


class PurchaseOrderPlanResponse(BaseModel):
    groups: list[PurchaseOrderPlanGroup] = Field(default_factory=list)
    unassigned: list[PurchaseOrderPlanLine] = Field(default_factory=list)


class PurchaseOrderFromSalesOrderLine(BaseModel):
    sales_order_line_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    supplier_product_id: UUID | None = None


class PurchaseOrderFromSalesOrderGroup(BaseModel):
    supplier_id: UUID
    warehouse_id: UUID | None = None
    expected_delivery_date: date | None = None
    currency_id: UUID | None = None
    lines: list[PurchaseOrderFromSalesOrderLine] = Field(min_length=1)


class PurchaseOrderFromSalesOrderRequest(BaseModel):
    groups: list[PurchaseOrderFromSalesOrderGroup] = Field(min_length=1)
    allow_overcommit: bool = False
