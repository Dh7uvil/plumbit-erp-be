"""Purchase invoice request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.schemas.related_documents import RelatedDocumentRef
from app.core.enums import (
    BillType,
    DiscountType,
    ExpenseCategory,
    InvoiceDocumentStatus,
    PaymentStatus,
    PlaceOfSupply,
    PurchaseInvoiceLineType,
    TaxTreatment,
)


class PurchaseInvoiceFilter(BaseFilter):
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
    supplier_id: UUID | None = None
    purchase_order_id: UUID | None = None
    goods_receipt_id: UUID | None = None
    bill_type: BillType | None = None
    payment_status: PaymentStatus | None = None
    invoice_date_from: date | None = None
    invoice_date_to: date | None = None

    @model_validator(mode="after")
    def validate_invoice_date_range(self) -> "PurchaseInvoiceFilter":
        if (
            self.invoice_date_from is not None
            and self.invoice_date_to is not None
            and self.invoice_date_from > self.invoice_date_to
        ):
            raise ValueError("invoice_date_from must be before or equal to invoice_date_to")
        return self


class PurchaseInvoiceLineInput(BaseModel):
    line_type: PurchaseInvoiceLineType = PurchaseInvoiceLineType.PRODUCT
    product_id: UUID | None = None
    description: str | None = None
    quantity: Decimal = Field(default=Decimal("1"), gt=0, max_digits=18, decimal_places=6)
    unit_id: UUID | None = None
    rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    purchase_order_line_id: UUID | None = None
    goods_receipt_id: UUID | None = None
    goods_receipt_line_id: UUID | None = None
    supplier_product_id: UUID | None = None
    supplier_sku: str | None = Field(default=None, max_length=80)
    expense_account_id: UUID | None = None
    expense_category: ExpenseCategory | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax_id: UUID | None = None

    @field_validator("description", "supplier_sku")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_line_shape(self) -> "PurchaseInvoiceLineInput":
        if self.line_type == PurchaseInvoiceLineType.EXPENSE:
            if self.expense_category is None:
                raise ValueError("Expense lines require expense_category")
            if self.rate is None:
                raise ValueError("Expense lines require a rate")
        elif self.product_id is None and not self.description:
            raise ValueError("Each product line requires a product_id or a description")
        if (self.goods_receipt_id is None) != (self.goods_receipt_line_id is None):
            raise ValueError("goods_receipt_id and goods_receipt_line_id must be set together")
        return self


class PurchaseInvoiceLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    line_type: PurchaseInvoiceLineType
    product_id: UUID | None
    description: str
    quantity: Decimal
    unit_id: UUID | None
    rate: Decimal
    purchase_order_line_id: UUID | None
    goods_receipt_id: UUID | None
    goods_receipt_line_id: UUID | None
    supplier_product_id: UUID | None
    supplier_sku: str | None
    expense_account_id: UUID | None
    expense_category: ExpenseCategory | None
    discount_type: DiscountType | None
    discount_value: Decimal | None
    discount_amount: Decimal
    tax_id: UUID | None
    tax_rate: Decimal
    tax_amount: Decimal
    amount: Decimal
    purchase_account_id: UUID | None
    grn_unit_cost: Decimal
    qty_debited: Decimal
    landed_cost_allocated: Decimal = Decimal("0")
    landed_cost_remaining: Decimal | None = None


class PurchaseInvoiceCreate(BaseModel):
    supplier_id: UUID
    bill_type: BillType = BillType.GOODS
    contact_id: UUID | None = None
    branch_id: UUID | None = None
    invoice_date: date | None = None
    purchase_order_id: UUID | None = None
    goods_receipt_id: UUID | None = None
    supplier_invoice_number: str | None = Field(default=None, max_length=80)
    supplier_invoice_date: date | None = None
    payment_terms_id: UUID | None = None
    currency_id: UUID | None = None
    notes: str | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    shipping_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    adjustment_amount: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=4)
    round_off_amount: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=4)
    place_of_supply: PlaceOfSupply | None = None
    is_reverse_charge: bool | None = None
    lines: list[PurchaseInvoiceLineInput] = Field(min_length=1)

    @field_validator("notes", "supplier_invoice_number")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PurchaseInvoiceUpdate(BaseModel):
    bill_type: BillType | None = None
    contact_id: UUID | None = None
    branch_id: UUID | None = None
    invoice_date: date | None = None
    purchase_order_id: UUID | None = None
    goods_receipt_id: UUID | None = None
    supplier_invoice_number: str | None = Field(default=None, max_length=80)
    supplier_invoice_date: date | None = None
    payment_terms_id: UUID | None = None
    currency_id: UUID | None = None
    notes: str | None = None
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    shipping_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    adjustment_amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)
    round_off_amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)
    place_of_supply: PlaceOfSupply | None = None
    is_reverse_charge: bool | None = None
    lines: list[PurchaseInvoiceLineInput] | None = None
    version: int | None = Field(default=None, ge=1)


class PurchaseInvoiceCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PurchaseInvoiceCreateFromPurchaseOrder(BaseModel):
    purchase_order_id: UUID
    invoice_date: date | None = None
    notes: str | None = None


class PurchaseInvoiceCreateFromGoodsReceipt(BaseModel):
    goods_receipt_id: UUID
    invoice_date: date | None = None
    notes: str | None = None


class PurchaseInvoiceResponse(BaseModel):
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
    bill_type: BillType
    supplier_id: UUID
    contact_id: UUID | None
    supplier_trn: str | None
    branch_id: UUID | None
    purchase_order_id: UUID | None
    goods_receipt_id: UUID | None
    supplier_invoice_number: str | None
    supplier_invoice_date: date | None
    payment_terms_id: UUID | None
    due_date: date | None
    tax_treatment: TaxTreatment
    place_of_supply: PlaceOfSupply
    is_reverse_charge: bool
    rcm_taxable_amount: Decimal
    rcm_tax_amount: Decimal
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
    amount_paid: Decimal
    amount_debited: Decimal
    balance_due: Decimal
    payment_status: PaymentStatus
    journal_entry_id: UUID | None
    reversal_journal_entry_id: UUID | None
    posted_at: datetime | None
    posted_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    is_overdue: bool = False
    is_partially_debited: bool = False
    is_fully_debited: bool = False
    available_actions: list[str] = Field(default_factory=list)
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    lines: list[PurchaseInvoiceLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
