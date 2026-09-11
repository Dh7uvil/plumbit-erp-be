"""Shared helpers for commercial-document Excel import."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from app.common.imex.http import mapping_or_suggested
from app.common.imex.schemas import ImexMappingEntry, ImportResult, ImportRowError
from app.common.imex.service import mapped_rows, parse_optional_decimal
from app.core.exceptions import ValidationError

_ZERO = Decimal("0")

COMMERCIAL_EXPORT_HEADERS = [
    "document_number",
    "document_date",
    "party_id",
    "line.item_code",
    "line.description",
    "line.quantity",
    "line.unit_price",
    "line.carton_qty",
    "line.packing_unit",
    "line.cbm",
    "line.weight",
]


def resolve_entries(mapping: Sequence[object]) -> list[ImexMappingEntry]:
    return [
        item if isinstance(item, ImexMappingEntry) else ImexMappingEntry.model_validate(item)
        for item in mapping
    ]


def load_mapped_rows(
    resource: str,
    *,
    filename: str | None,
    content: bytes,
    mapping: Sequence[object],
) -> list[dict[str, str]]:
    resolved = mapping_or_suggested(
        resource,
        filename=filename,
        content=content,
        mapping=resolve_entries(mapping),
    )
    return mapped_rows(filename=filename, content=content, mapping=resolved)


def group_fill_forward(
    rows: Sequence[dict[str, str]],
    keys: Sequence[str],
) -> dict[tuple[str, ...], list[tuple[int, dict[str, str]]]]:
    groups: dict[tuple[str, ...], list[tuple[int, dict[str, str]]]] = {}
    last = {key: "" for key in keys}
    for index, row in enumerate(rows, start=2):
        current: list[str] = []
        for key in keys:
            token = (row.get(key) or "").strip() or last[key]
            last[key] = token
            current.append(token)
        groups.setdefault(tuple(value.lower() for value in current), []).append((index, row))
    return groups


def require_line_quantity(item: dict[str, str]) -> Decimal:
    qty = parse_optional_decimal(item.get("line.quantity"))
    if qty is None or qty <= _ZERO:
        raise ValidationError("Each line requires a quantity")
    return qty


def packing_kwargs(item: dict[str, str], *, sku: str) -> dict[str, object]:
    return {
        "description": (item.get("line.description") or "").strip() or sku or None,
        "carton_qty": parse_optional_decimal(item.get("line.carton_qty")),
        "packing_unit": (item.get("line.packing_unit") or "").strip() or None,
        "cbm": parse_optional_decimal(item.get("line.cbm")),
        "weight": parse_optional_decimal(item.get("line.weight")),
        "item_code": (item.get("line.item_code") or sku or None),
    }


def commercial_export_row(row: object, line: object, *, party_id: UUID) -> list[object]:
    document_date = (
        getattr(row, "document_date", None)
        or getattr(row, "invoice_date", None)
        or getattr(row, "proforma_date", None)
        or getattr(row, "quote_date", None)
        or getattr(row, "order_date", None)
    )
    rate = getattr(line, "rate", None)
    return [
        getattr(row, "document_number", ""),
        document_date.isoformat() if document_date is not None else "",
        str(party_id),
        getattr(line, "item_code", None) or "",
        getattr(line, "description", "") or "",
        str(getattr(line, "quantity", "")),
        str(rate) if rate is not None else "",
        str(getattr(line, "carton_qty", None) or ""),
        getattr(line, "packing_unit", None) or "",
        str(getattr(line, "cbm", None) or ""),
        str(getattr(line, "weight", None) or ""),
    ]


def import_result(created_ids: list[UUID], errors: list[ImportRowError]) -> ImportResult:
    return ImportResult(
        created_ids=created_ids,
        errors=errors,
        created_count=len(created_ids),
        error_count=len(errors),
    )
