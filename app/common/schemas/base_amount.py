"""Shared base-currency response fields for money-bearing APIs."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class BaseAmountFields(BaseModel):
    """Document amount in foreign currency with org-base equivalent."""

    foreign_amount: Decimal | None = None
    base_amount: Decimal | None = None
    base_currency_id: UUID | None = None
    base_currency_code: str | None = None
    exchange_rate: Decimal | None = Field(default=None, description="Foreign per one base unit")
