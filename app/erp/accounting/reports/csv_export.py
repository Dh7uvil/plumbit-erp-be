"""CSV export helper for Stage I report endpoints."""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from pydantic import BaseModel

_CSV_ACCEPT = "text/csv"


def wants_csv(request: Request, format: str | None) -> bool:
    if format is not None and format.strip().lower() == "csv":
        return True
    accept = (request.headers.get("accept") or "").lower()
    return _CSV_ACCEPT in accept


def csv_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def rows_from_models(items: list[BaseModel]) -> tuple[list[str], list[dict[str, str]]]:
    if not items:
        return [], []
    dumped = [item.model_dump(mode="json") for item in items]
    fields = [key for key, value in dumped[0].items() if not isinstance(value, list)]
    rows = [{key: csv_cell(row.get(key)) for key in fields} for row in dumped]
    return fields, rows


def csv_response(filename: str, fieldnames: list[str], rows: list[dict[str, Any]]) -> Response:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: csv_cell(row.get(key)) for key in fieldnames})
    return Response(
        content=buffer.getvalue(),
        media_type=_CSV_ACCEPT,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
