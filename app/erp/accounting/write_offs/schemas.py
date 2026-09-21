"""Request bodies for invoice write-offs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class InvoiceWriteOffRequest(BaseModel):
    amount: Decimal = Field(gt=Decimal("0"))
    write_off_date: date
    reason: str | None = None
    expense_account_id: UUID | None = None
    version: int | None = None


class InvoiceWriteOffReverseRequest(BaseModel):
    write_off_id: UUID
    reversal_date: date
    reason: str | None = None
    version: int | None = None
