"""Trading history response schemas."""

from datetime import date
from decimal import Decimal
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, model_validator

from app.common.schemas.filters import BaseFilter


class TradingPartyAggregate(BaseModel):
    party_id: UUID
    party_name: str
    total_quantity: Decimal
    dispatch_count: int
    first_date: date
    last_date: date
    last_rate: Decimal
    last_posted_by: UUID | None = None
    salesperson_id: UUID | None = None
    invoiced_quantity: Decimal = Decimal("0")
    revenue: Decimal = Decimal("0")


class TradingProductAggregate(BaseModel):
    product_id: UUID
    product_name: str
    sku: str
    total_quantity: Decimal
    dispatch_count: int
    first_date: date
    last_date: date
    last_rate: Decimal
    last_posted_by: UUID | None = None
    salesperson_id: UUID | None = None
    invoiced_quantity: Decimal = Decimal("0")
    revenue: Decimal = Decimal("0")


class TradingHistoryLine(BaseModel):
    document_id: UUID
    document_number: str
    document_date: date
    product_id: UUID
    product_name: str
    sku: str
    party_id: UUID
    party_name: str
    warehouse_id: UUID
    quantity: Decimal
    rate: Decimal
    unit_cost: Decimal | None = None
    margin: Decimal | None = None
    posted_by: UUID | None = None
    salesperson_id: UUID | None = None
    invoiced_quantity: Decimal = Decimal("0")
    revenue: Decimal = Decimal("0")
    billed_cost: Decimal | None = None


class TradingHistoryFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "document_date",
            "document_number",
            "quantity",
            "rate",
            "revenue",
            "party_name",
            "product_name",
            "sku",
        }
    )
    sort_by: str = "document_date"
    party_id: UUID | None = None
    product_id: UUID | None = None
    warehouse_id: UUID | None = None
    document_date_from: date | None = None
    document_date_to: date | None = None
    posting_status: Literal["POSTED", "ALL", "UNPOSTED"] = "POSTED"

    @model_validator(mode="after")
    def validate_document_date_range(self) -> "TradingHistoryFilter":
        if (
            self.document_date_from is not None
            and self.document_date_to is not None
            and self.document_date_from > self.document_date_to
        ):
            raise ValueError("document_date_from must be before or equal to document_date_to")
        return self


class ProductPurchaseDetailsFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"document_date", "document_number", "quantity", "rate", "amount", "party_name"}
    )
    sort_by: str = "document_date"
    kind: Literal["LOCAL", "IMPORT"]
    posting_status: Literal["ALL", "POSTED", "UNPOSTED"] = "ALL"
    name: str | None = None


class ProductPurchaseDetailLine(BaseModel):
    line_id: UUID
    document_type: Literal["PURCHASE_INVOICE", "GOODS_RECEIPT"] = "PURCHASE_INVOICE"
    document_id: UUID
    document_number: str
    document_date: date
    product_id: UUID
    description: str
    party_id: UUID
    party_name: str
    quantity: Decimal
    rate: Decimal
    amount: Decimal
    currency_code: str | None = None
    warehouse_id: UUID | None = None
    warehouse_name: str | None = None
    supplier_invoice_number: str | None = None
    lc_date: date | None = None
    lc_number: str | None = None
    fc_rate: Decimal | None = None
    rate_lcy: Decimal | None = None
    amount_lcy: Decimal | None = None
    exchange_rate: Decimal | None = None
    branch_id: UUID | None = None
    branch_name: str | None = None
    is_posted: bool = False


class TradingAggregateFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "party_name",
            "sku",
            "product_name",
            "total_quantity",
            "revenue",
            "last_date",
            "dispatch_count",
        }
    )
    sort_by: str = "last_date"
