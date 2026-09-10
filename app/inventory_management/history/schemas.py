"""Trading history response schemas."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, model_validator


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


class TradingHistoryFilter(BaseModel):
    party_id: UUID | None = None
    product_id: UUID | None = None
    warehouse_id: UUID | None = None
    document_date_from: date | None = None
    document_date_to: date | None = None

    @model_validator(mode="after")
    def validate_document_date_range(self) -> "TradingHistoryFilter":
        if (
            self.document_date_from is not None
            and self.document_date_to is not None
            and self.document_date_from > self.document_date_to
        ):
            raise ValueError("document_date_from must be before or equal to document_date_to")
        return self
