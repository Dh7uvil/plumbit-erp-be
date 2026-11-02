"""Quantity breakdown helpers (PCS / PKT / remainder)."""

from decimal import Decimal

from app.inventory_management.products.inquiry_quantities import (
    build_quantity_rows,
    format_secondary_packing_label,
    format_unit2_package_text,
    inquiry_secondary_display,
    quantity_unit_breakdown,
)


def test_format_secondary_packing_label_pcs_per_ctn() -> None:
    assert format_secondary_packing_label(Decimal("200"), "CTN") == "200.00 PCS / CTN"


def test_format_secondary_packing_label_pcs_per_pcs() -> None:
    assert format_secondary_packing_label(Decimal("1"), "PCS") == "1.00 PCS / PCS"


def test_inquiry_secondary_display_defaults() -> None:
    factor, code = inquiry_secondary_display(
        secondary_unit_factor=None,
        unit2_code=None,
    )
    assert factor == Decimal("1")
    assert code == "PCS"


def test_build_quantity_rows_without_stored_factor_uses_default_one() -> None:
    rows = build_quantity_rows(
        qty_on_hand=Decimal("5000"),
        qty_opened=Decimal("0"),
        qty_committed=Decimal("0"),
        net_available=Decimal("5000"),
        factor=Decimal("1"),
    )
    assert rows.on_hand is not None
    assert rows.on_hand.unit2_qty == Decimal("5000")
    assert rows.on_hand.remainder_qty == Decimal("0")


def test_quantity_unit_breakdown_with_factor() -> None:
    row = quantity_unit_breakdown(Decimal("540"), Decimal("5"))
    assert row is not None
    assert row.unit_qty == Decimal("540")
    assert row.unit2_qty == Decimal("108")
    assert row.remainder_qty == Decimal("0")


def test_format_unit2_package_text_loose_only() -> None:
    assert format_unit2_package_text(Decimal("0"), Decimal("7"), "PCS", "PKT") == "7.00 PCS loose"


def test_format_unit2_package_text_full_and_loose() -> None:
    text = format_unit2_package_text(Decimal("61"), Decimal("15"), "PCS", "CTN")
    assert text == "61.00 CTN & 15.00 PCS loose"


def test_build_quantity_rows_net_available() -> None:
    rows = build_quantity_rows(
        qty_on_hand=Decimal("540"),
        qty_opened=Decimal("20"),
        qty_committed=Decimal("420"),
        net_available=Decimal("100"),
        factor=Decimal("5"),
    )
    assert rows.net_available is not None
    assert rows.net_available.unit_qty == Decimal("100")
    assert rows.net_available.unit2_qty == Decimal("20")
