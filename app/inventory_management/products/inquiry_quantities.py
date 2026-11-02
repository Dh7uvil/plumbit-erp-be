"""Quantity breakdown helpers (PCS / PKT / remainder)."""

from decimal import Decimal

from app.common.utils.currency import format_quantity_display
from app.inventory_management.products.schemas import (
    ProductInquiryQuantityRows,
    ProductQuantityUnitBreakdown,
)

_ZERO = Decimal("0")


def quantity_unit_breakdown(
    qty: Decimal, factor: Decimal | None
) -> ProductQuantityUnitBreakdown | None:
    if factor is None or factor <= 0:
        return ProductQuantityUnitBreakdown(
            unit_qty=qty,
            unit2_qty=_ZERO,
            remainder_qty=_ZERO,
        )
    unit2_count = int(qty // factor)
    remainder = qty - Decimal(unit2_count) * factor
    return ProductQuantityUnitBreakdown(
        unit_qty=qty,
        unit2_qty=Decimal(unit2_count),
        remainder_qty=remainder,
    )


def format_secondary_packing_label(
    factor: Decimal,
    unit2_code: str,
) -> str:
    """Display label: pieces per unit 2, e.g. ``200.00 PCS / CTN``."""
    u2 = (unit2_code or "PCS").strip() or "PCS"
    qty = factor if factor > 0 else Decimal("1")
    return f"{format_quantity_display(qty)} PCS / {u2}"


def inquiry_secondary_display(
    *,
    secondary_unit_factor: Decimal | None,
    unit2_code: str | None,
) -> tuple[Decimal, str]:
    """Effective factor and unit-2 code for inquiry UI when unit 2 is unset."""
    factor = secondary_unit_factor if secondary_unit_factor and secondary_unit_factor > 0 else Decimal(
        "1"
    )
    u2 = (unit2_code or "PCS").strip() or "PCS"
    return factor, u2


def format_unit2_package_text(
    unit2_qty: Decimal,
    remainder_qty: Decimal,
    unit_code: str,
    unit2_code: str,
) -> str:
    u2_qty = format_quantity_display(unit2_qty)
    rem_qty = format_quantity_display(remainder_qty)
    if unit2_qty > 0 and remainder_qty > 0:
        return f"{u2_qty} {unit2_code} & {rem_qty} {unit_code} loose"
    if unit2_qty > 0:
        return f"{u2_qty} {unit2_code}"
    if remainder_qty > 0:
        return f"{rem_qty} {unit_code} loose"
    return f"{format_quantity_display(_ZERO)} {unit2_code}"


def build_quantity_rows(
    *,
    qty_on_hand: Decimal,
    qty_opened: Decimal,
    qty_committed: Decimal,
    net_available: Decimal,
    factor: Decimal | None,
) -> ProductInquiryQuantityRows:
    return ProductInquiryQuantityRows(
        on_hand=quantity_unit_breakdown(qty_on_hand, factor),
        opened=quantity_unit_breakdown(qty_opened, factor),
        committed=quantity_unit_breakdown(qty_committed, factor),
        net_available=quantity_unit_breakdown(net_available, factor),
    )
