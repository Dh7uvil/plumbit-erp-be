"""Shared related-document and remaining-qty payload fragments."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class RelatedDocumentRef(BaseModel):
    document_type: str
    document_id: UUID
    document_number: str
    status: str
    relationship: str
    document_date: date | None = None
    quantity_summary: str | None = None
    amount_summary: str | None = None


class QuantityProgress(BaseModel):
    ordered: Decimal
    fulfilled: Decimal
    invoiced: Decimal
    remaining_to_fulfill: Decimal
    remaining_to_invoice: Decimal
