"""Shared discount field validation for commercial documents."""

from __future__ import annotations

from decimal import Decimal
from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.core.enums import DiscountType

_MAX_PERCENT = Decimal("100")


class DiscountFieldsMixin(BaseModel):
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)

    @model_validator(mode="after")
    def validate_percentage_discount_cap(self) -> Self:
        if (
            self.discount_type == DiscountType.PERCENTAGE
            and self.discount_value is not None
            and self.discount_value > _MAX_PERCENT
        ):
            raise ValueError("Percentage discount cannot exceed 100")
        return self


def assert_discount_bounds(
    discount_type: DiscountType | None,
    discount_value: Decimal | None,
) -> None:
    """Service-level guard when values bypass schema validation."""

    from app.core.exceptions import ValidationError

    if (
        discount_type == DiscountType.PERCENTAGE
        and discount_value is not None
        and discount_value > _MAX_PERCENT
    ):
        raise ValidationError("Percentage discount cannot exceed 100")
