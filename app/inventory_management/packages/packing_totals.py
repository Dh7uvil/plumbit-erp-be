"""Pure helpers for package and shipment packing rollups."""

from __future__ import annotations

from decimal import Decimal

from app.common.utils.currency import quantize_quantity

_ZERO = Decimal("0")
_CM3_PER_M3 = Decimal("1000000")
_MM3_PER_M3 = Decimal("1000000000")
_IN3_PER_M3 = Decimal("61023.744095")


def weight_to_kg(weight: Decimal | None, unit: str | None) -> Decimal | None:
    if weight is None:
        return None
    normalized = (unit or "kg").strip().lower()
    if normalized in {"kg", "kgs", "kilogram", "kilograms"}:
        return quantize_quantity(weight)
    if normalized in {"g", "gram", "grams"}:
        return quantize_quantity(weight / Decimal("1000"))
    if normalized in {"lb", "lbs", "pound", "pounds"}:
        return quantize_quantity(weight * Decimal("0.453592"))
    return quantize_quantity(weight)


def cbm_from_dimensions(
    length: Decimal | None,
    width: Decimal | None,
    height: Decimal | None,
    unit: str | None,
) -> Decimal | None:
    if length is None or width is None or height is None:
        return None
    if length <= _ZERO or width <= _ZERO or height <= _ZERO:
        return None
    volume = length * width * height
    normalized = (unit or "cm").strip().lower()
    if normalized in {"m", "meter", "meters"}:
        return quantize_quantity(volume)
    if normalized in {"cm", "centimeter", "centimeters"}:
        return quantize_quantity(volume / _CM3_PER_M3)
    if normalized in {"mm", "millimeter", "millimeters"}:
        return quantize_quantity(volume / _MM3_PER_M3)
    if normalized in {"in", "inch", "inches"}:
        return quantize_quantity(volume / _IN3_PER_M3)
    return quantize_quantity(volume / _CM3_PER_M3)


def sum_line_cbm(lines: list[object]) -> Decimal | None:
    total = _ZERO
    has_value = False
    for line in lines:
        cbm = getattr(line, "cbm", None)
        if cbm is None:
            continue
        has_value = True
        total += cbm
    return quantize_quantity(total) if has_value else None


def apply_package_header_rollups(
    header: dict[str, object], line_rows: list[dict[str, object]]
) -> None:
    """Fill total_cbm and optional gross/net weight from lines or dimensions."""

    line_objs = [type("Line", (), row)() for row in line_rows]
    for obj, row in zip(line_objs, line_rows, strict=True):
        for key, value in row.items():
            setattr(obj, key, value)

    total_cbm = sum_line_cbm(line_objs)
    if total_cbm is None:
        total_cbm = cbm_from_dimensions(
            header.get("length"),  # type: ignore[arg-type]
            header.get("width"),  # type: ignore[arg-type]
            header.get("height"),  # type: ignore[arg-type]
            header.get("dimension_unit"),  # type: ignore[arg-type]
        )
    header["total_cbm"] = total_cbm

    if header.get("gross_weight") is None:
        rolled = sum_line_weight_kg(line_objs, weight_unit=header.get("weight_unit"))  # type: ignore[arg-type]
        if rolled is not None:
            header["gross_weight"] = rolled
            if header.get("net_weight") is None:
                header["net_weight"] = rolled


def sum_line_weight_kg(lines: list[object], *, weight_unit: str | None) -> Decimal | None:
    total = _ZERO
    has_value = False
    for line in lines:
        weight = getattr(line, "weight", None)
        if weight is None:
            continue
        converted = weight_to_kg(weight, weight_unit)
        if converted is None:
            continue
        has_value = True
        total += converted
    return quantize_quantity(total) if has_value else None
