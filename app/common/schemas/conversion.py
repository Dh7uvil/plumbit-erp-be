"""Shared request fragments for partial document conversion."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ConversionLineInput(BaseModel):
    source_line_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
