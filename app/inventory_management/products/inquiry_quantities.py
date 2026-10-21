"""Winsoft-style quantity breakdown helpers."""

from decimal import Decimal

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
