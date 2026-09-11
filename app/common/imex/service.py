"""Shared import preview/template/export helpers. Writers live in owning slices."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi.responses import Response

from app.common.imex.catalogs import CATALOGS
from app.common.imex.parser import (
    apply_mapping,
    columns_from_headers,
    parse_tabular,
    sample_rows,
    suggest_mapping,
    write_xlsx,
)
from app.common.imex.schemas import (
    ImexField,
    ImexMappingEntry,
    ImportPreviewResponse,
)
from app.core.exceptions import ValidationError


def catalog_for(resource: str) -> list[ImexField]:
    fields = CATALOGS.get(resource)
    if fields is None:
        raise ValidationError(f"Import/export is not enabled for {resource}")
    return fields


def preview_file(
    resource: str, *, filename: str | None, content: bytes
) -> ImportPreviewResponse:
    fields = catalog_for(resource)
    headers, rows = parse_tabular(filename, content)
    return ImportPreviewResponse(
        columns=columns_from_headers(headers),
        suggested_mapping=suggest_mapping(headers, fields),
        sample_rows=sample_rows(headers, rows),
        row_count=len(rows),
    )


def mapped_rows(
    *,
    filename: str | None,
    content: bytes,
    mapping: Sequence[ImexMappingEntry],
) -> list[dict[str, str]]:
    headers, rows = parse_tabular(filename, content)
    if not mapping:
        raise ValidationError("Column mapping is required")
    return apply_mapping(headers, rows, mapping)


def template_response(resource: str) -> Response:
    fields = catalog_for(resource)
    headers = [field.name for field in fields]
    body = write_xlsx(headers, [])
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{resource}-import-template.xlsx"'
        },
    )


def export_response(
    resource: str, headers: Sequence[str], rows: Sequence[Sequence[object]]
) -> Response:
    body = write_xlsx(headers, rows)
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{resource}-export.xlsx"'},
    )


def parse_optional_date(value: str | None) -> date | None:
    token = (value or "").strip()
    if not token:
        return None
    try:
        return date.fromisoformat(token[:10])
    except ValueError:
        return None


def parse_optional_decimal(value: str | None) -> Decimal | None:
    token = (value or "").strip().replace(",", "")
    if not token:
        return None
    try:
        return Decimal(token)
    except InvalidOperation:
        return None
