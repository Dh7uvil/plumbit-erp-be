"""Line remaining-qty helpers for partial document conversion."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from app.common.utils.currency import quantize_money, quantize_quantity
from app.core.exceptions import ValidationError

_ZERO = Decimal("0")


def remaining_qty(quantity: Decimal, qty_converted: Decimal) -> Decimal:
    leftover = quantize_quantity(quantity - qty_converted)
    return leftover if leftover > _ZERO else _ZERO


def allocate_conversion_qty(
    *,
    lines: Sequence[tuple[UUID, Decimal, Decimal]],
    requested: Sequence[tuple[UUID, Decimal]] | None,
    empty_message: str,
    exceed_message: str = "Converted quantity exceeds remaining quantity on a source line",
) -> list[tuple[UUID, Decimal]]:
    """Return (source_line_id, qty) pairs. `requested` None means all remaining qty."""

    remaining_by_id = {
        line_id: remaining_qty(quantity, converted) for line_id, quantity, converted in lines
    }
    if requested is None:
        allocations = [
            (line_id, leftover)
            for line_id, leftover in remaining_by_id.items()
            if leftover > _ZERO
        ]
        if not allocations:
            raise ValidationError(empty_message)
        return allocations

    seen: set[UUID] = set()
    allocations: list[tuple[UUID, Decimal]] = []
    for line_id, quantity in requested:
        if line_id in seen:
            raise ValidationError("Duplicate source line in conversion request")
        seen.add(line_id)
        leftover = remaining_by_id.get(line_id)
        if leftover is None:
            raise ValidationError("Source line does not belong to this document")
        qty = quantize_quantity(quantity)
        if qty > leftover:
            raise ValidationError(exceed_message)
        if qty <= _ZERO:
            continue
        allocations.append((line_id, qty))
    if not allocations:
        raise ValidationError(empty_message)
    return allocations


def remaining_after_allocations(
    lines: Sequence[tuple[UUID, Decimal, Decimal]],
    allocations: Sequence[tuple[UUID, Decimal]],
) -> Decimal:
    applied = dict(allocations)
    total = _ZERO
    for line_id, quantity, converted in lines:
        leftover = remaining_qty(quantity, converted) - applied.get(line_id, _ZERO)
        if leftover > _ZERO:
            total += leftover
    return quantize_quantity(total)


def copy_source_commercial_header(
    header: dict[str, object],
    *,
    exchange_rate: Decimal,
    base_currency_id: UUID,
    bill_to_snapshot: str | None,
    ship_to_snapshot: str | None,
) -> None:
    """Keep the source document's FX and address snapshots on the child draft."""

    header["exchange_rate"] = exchange_rate
    header["base_currency_id"] = base_currency_id
    grand = header["grand_total"]
    header["base_amount"] = quantize_money(grand * exchange_rate)
    header["bill_to_snapshot"] = bill_to_snapshot
    header["ship_to_snapshot"] = ship_to_snapshot


def quantity_summary(quantities: Sequence[Decimal]) -> str:
    total = sum(quantities, _ZERO)
    return f"{len(quantities)} lines · qty {total}"
