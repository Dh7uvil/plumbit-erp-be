"""Unit tests for package packing rollups."""

from decimal import Decimal

from app.inventory_management.packages.packing_totals import (
    apply_package_header_rollups,
    cbm_from_dimensions,
    weight_to_kg,
)


def test_cbm_from_dimensions_in_centimeters() -> None:
    assert cbm_from_dimensions(Decimal("100"), Decimal("50"), Decimal("20"), "cm") == Decimal(
        "0.100000"
    )


def test_weight_to_kg_converts_pounds() -> None:
    assert weight_to_kg(Decimal("10"), "lb") == Decimal("4.535920")


def test_apply_package_header_rollups_from_lines() -> None:
    header: dict[str, object] = {"weight_unit": "kg"}
    line_rows = [{"cbm": Decimal("1.5"), "weight": Decimal("12")}]
    apply_package_header_rollups(header, line_rows)
    assert header["total_cbm"] == Decimal("1.500000")
    assert header["gross_weight"] == Decimal("12.000000")
