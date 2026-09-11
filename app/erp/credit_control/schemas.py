"""Credit-control exposure payloads."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.schemas.warnings import DocumentWarning


class CreditExposure(BaseModel):
    customer_id: UUID
    currency_id: UUID
    credit_limit: Decimal | None
    exposure: Decimal
    this_document: Decimal = Decimal("0")
    available: Decimal | None = None
    posted_ar: Decimal = Decimal("0")
    opening_ar: Decimal = Decimal("0")
    unapplied_receipts: Decimal = Decimal("0")
    unapplied_credits: Decimal = Decimal("0")
    open_orders: Decimal = Decimal("0")
    policy: str
    warnings: list[DocumentWarning] = Field(default_factory=list)
