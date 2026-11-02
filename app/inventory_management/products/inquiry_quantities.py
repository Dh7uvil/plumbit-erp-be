"""Quantity breakdown helpers (PCS / PKT / remainder)."""

from decimal import ROUND_DOWN, Decimal

from app.common.utils.currency import format_quantity_display, quantize_quantity
from app.inventory_management.products.schemas import (
    ProductInquiryQuantityRows,
    ProductQuantityUnitBreakdown,
)

_ZERO = Decimal("0")
_DUST = Decimal("0.000001")


def _display_qty(value: Decimal) -> Decimal:
    q = quantize_quantity(value)
    if q.copy_abs() < _DUST:
        return _ZERO
    return q


def _is_pcs(code: str | None) -> bool:
    return (code or "").strip().upper() == "PCS"


def is_inverted_packaging(
    base_unit_code: str | None,
    unit2_code: str | None,
) -> bool:
    """Stock unit is a package and unit 2 is pieces (e.g. CTN + PCS)."""
    base = (base_unit_code or "").strip()
    return bool(base) and _is_pcs(unit2_code) and not _is_pcs(base_unit_code)


def pieces_per_for_inverted(
    *,
    pieces_per_unit: Decimal | None,
    secondary_unit_factor: Decimal | None,
) -> Decimal:
    if pieces_per_unit is not None and pieces_per_unit > 0:
        return pieces_per_unit
    if secondary_unit_factor is not None and secondary_unit_factor > 0:
        return secondary_unit_factor
    return Decimal("1")


def format_base_packing_label(factor: Decimal, base_unit_code: str) -> str:
    """Display label: pieces per stock unit, e.g. ``100.00 PCS / CTN``."""
    u1 = (base_unit_code or "Unit").strip() or "Unit"
    qty = factor if factor > 0 else Decimal("1")
    return f"{format_quantity_display(qty)} PCS / {u1}"


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
        unit_qty=_display_qty(qty),
        unit2_qty=_display_qty(Decimal(unit2_count)),
        remainder_qty=_display_qty(remainder),
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


def quantity_unit_breakdown_inverted(
    qty_in_base: Decimal,
    pieces_per_base: Decimal,
) -> ProductQuantityUnitBreakdown:
    if pieces_per_base <= 0:
        return ProductQuantityUnitBreakdown(
            unit_qty=_display_qty(qty_in_base),
            unit2_qty=_ZERO,
            remainder_qty=_ZERO,
        )
    qty = _display_qty(qty_in_base)
    factor = pieces_per_base
    # Legacy balances stored piece counts in the base (carton) unit before conversion on post.
    if factor > 1 and qty >= factor:
        cartons_if_pieces = qty / factor
        if (
            cartons_if_pieces == cartons_if_pieces.to_integral_value()
            and cartons_if_pieces >= 10
        ):
            return ProductQuantityUnitBreakdown(
                unit_qty=_display_qty(cartons_if_pieces),
                unit2_qty=qty,
                remainder_qty=_ZERO,
            )
    full_cartons = qty.to_integral_value(rounding=ROUND_DOWN)
    remainder = (qty - full_cartons) * factor
    return ProductQuantityUnitBreakdown(
        unit_qty=qty,
        unit2_qty=_display_qty(qty * factor),
        remainder_qty=_display_qty(remainder),
    )


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


def build_quantity_rows_inverted(
    *,
    qty_on_hand: Decimal,
    qty_opened: Decimal,
    qty_committed: Decimal,
    net_available: Decimal,
    pieces_per_base: Decimal,
) -> ProductInquiryQuantityRows:
    return ProductInquiryQuantityRows(
        on_hand=quantity_unit_breakdown_inverted(qty_on_hand, pieces_per_base),
        opened=quantity_unit_breakdown_inverted(qty_opened, pieces_per_base),
        committed=quantity_unit_breakdown_inverted(qty_committed, pieces_per_base),
        net_available=quantity_unit_breakdown_inverted(net_available, pieces_per_base),
    )
