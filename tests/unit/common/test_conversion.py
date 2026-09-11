"""Unit tests for partial conversion remaining-qty helpers."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.common.utils.conversion import allocate_conversion_qty, remaining_qty
from app.core.exceptions import ValidationError


def test_allocate_none_uses_all_remaining() -> None:
    first = uuid4()
    second = uuid4()
    allocations = allocate_conversion_qty(
        lines=[
            (first, Decimal("2"), Decimal("0")),
            (second, Decimal("3"), Decimal("3")),
        ],
        requested=None,
        empty_message="nothing left",
    )
    assert allocations == [(first, Decimal("2"))]


def test_allocate_rejects_over_conversion() -> None:
    line_id = uuid4()
    with pytest.raises(ValidationError, match="exceeds remaining"):
        allocate_conversion_qty(
            lines=[(line_id, Decimal("2"), Decimal("1"))],
            requested=[(line_id, Decimal("2"))],
            empty_message="nothing left",
        )


def test_remaining_qty_floors_at_zero() -> None:
    assert remaining_qty(Decimal("1"), Decimal("2")) == Decimal("0")
