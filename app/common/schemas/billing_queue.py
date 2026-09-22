"""Shared billing-queue row shapes for purchase documents."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class OutstandingBillLine(BaseModel):
    line_id: UUID
    line_number: int
    description: str
    quantity: Decimal
    qty_fulfilled: Decimal
    qty_remaining: Decimal = Field(ge=0)


class PurchaseOrderBillingQueueItem(BaseModel):
    id: UUID
    document_number: str
    supplier_id: UUID
    order_date: date
    status: str
    billing_status: str
    currency_id: UUID
    lines: list[OutstandingBillLine] = Field(default_factory=list)


class GoodsReceiptBillingQueueItem(BaseModel):
    id: UUID
    document_number: str
    supplier_id: UUID
    purchase_order_id: UUID | None
    document_date: date
    status: str
    currency_id: UUID | None
    lines: list[OutstandingBillLine] = Field(default_factory=list)
