"""CSV export helper for Stage I report endpoints."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from fastapi import Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.common.utils.currency import format_money_display, format_quantity_display

_CSV_ACCEPT = "text/csv"

CsvFieldClass = Literal["money", "quantity", "percent", "other"]

_FX_FIELDS = frozenset({"exchange_rate"})
_INTEGER_FIELDS = frozenset(
    {
        "count",
        "days",
        "days_elapsed",
        "decimal_places",
        "deliveries_today",
        "export_evidence_exceptions",
        "line_number",
        "net_days",
        "next_number",
        "overdue_ap_count",
        "overdue_ar_count",
        "receipts_today",
        "revision_number",
        "total_packages",
        "users_count",
        "version",
        "window_days",
    }
)
_PERCENT_FIELDS = frozenset({"margin_percent", "percent", "tax_rate"})
_QUANTITY_FIELDS = frozenset(
    {
        "cbm",
        "carton_qty",
        "gross_weight",
        "height",
        "length",
        "net_weight",
        "quantity",
        "reorder_level",
        "weight",
        "width",
    }
)
_MONEY_FIELDS = frozenset(
    {
        "amount",
        "available_credit",
        "balance_due",
        "cash_closing",
        "cash_opening",
        "credit",
        "credit_limit",
        "current",
        "current_earnings",
        "debit",
        "difference",
        "net_change",
        "net_profit",
        "net_vat",
        "outstanding",
        "overdue",
        "price",
        "rate",
        "recoverable_input_vat",
        "subtotal",
        "total",
        "total_cogs",
        "total_operating_expense",
        "total_expense",
        "total_income",
        "gross_profit",
        "unapplied_credits",
        "value_in",
        "value_out",
    }
)
_MONEY_SUFFIXES = (
    "_amount",
    "_applied",
    "_assets",
    "_balance",
    "_base",
    "_charges",
    "_closing",
    "_cost",
    "_credit",
    "_credited",
    "_debit",
    "_debited",
    "_due",
    "_earnings",
    "_equity",
    "_expense",
    "_income",
    "_liabilities",
    "_limit",
    "_opening",
    "_paid",
    "_profit",
    "_received",
    "_refunded",
    "_total",
    "_unapplied",
    "_value",
    "_vat",
)


def wants_csv(request: Request, format: str | None) -> bool:
    if format is not None and format.strip().lower() in {"csv", "xlsx", "xls", "pdf"}:
        return True
    accept = (request.headers.get("accept") or "").lower()
    return (
        _CSV_ACCEPT in accept
        or "application/vnd.ms-excel" in accept
        or "spreadsheetml" in accept
        or "application/pdf" in accept
    )


def wants_excel(format: str | None) -> bool:
    return format is not None and format.strip().lower() in {"xlsx", "xls"}


def wants_pdf(format: str | None) -> bool:
    return format is not None and format.strip().lower() == "pdf"


def wants_xlsx(format: str | None) -> bool:
    return format is not None and format.strip().lower() == "xlsx"


def csv_field_class(field: str) -> CsvFieldClass:
    if field in _FX_FIELDS or field.endswith("exchange_rate"):
        return "other"
    if field in _INTEGER_FIELDS or field.endswith("_count") or field.endswith("_days"):
        return "other"
    if field in _PERCENT_FIELDS or field.endswith(("_percent", "_pct", "_percentage")):
        return "percent"
    if (
        field in _QUANTITY_FIELDS
        or field.startswith("qty_")
        or field.endswith(("_qty", "_quantity"))
    ):
        return "quantity"
    if field in _MONEY_FIELDS or field.endswith(_MONEY_SUFFIXES):
        return "money"
    if field.startswith("days_"):
        return "money"
    if field.endswith("_rate"):
        return "money"
    return "other"


def csv_cell(value: object, field: str | None = None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool | UUID | date | datetime):
        return str(value)
    if field is not None:
        kind = csv_field_class(field)
        if kind in {"money", "quantity", "percent"}:
            formatted = _format_decimal_cell(value, kind)
            if formatted is not None:
                return formatted
    return str(value)


def rows_from_models(items: list[BaseModel]) -> tuple[list[str], list[dict[str, Any]]]:
    if not items:
        return [], []
    dumped = [item.model_dump(mode="json") for item in items]
    fields = [key for key, value in dumped[0].items() if not isinstance(value, list)]
    rows = [{key: row.get(key) for key in fields} for row in dumped]
    return fields, rows


def csv_response(
    filename: str,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
    *,
    excel: bool = False,
    currency_code: str | None = None,
) -> Response:
    buffer = io.StringIO()
    if excel:
        buffer.write("\ufeff")
    if currency_code:
        buffer.write(f"# Monetary amounts in {currency_code}\n")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: csv_cell(row.get(key), key) for key in fieldnames})
    download_name = filename
    media_type = _CSV_ACCEPT
    if excel:
        download_name = filename.rsplit(".", 1)[0] + ".xls"
        media_type = "application/vnd.ms-excel"
    return Response(
        content=buffer.getvalue(),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


def table_download(
    filename: str,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
    *,
    export_format: str | None,
    currency_code: str | None = None,
) -> Response:
    """CSV, real xlsx, legacy xls (CSV), or a text PDF of the same rows."""

    kind = (export_format or "csv").strip().lower()
    if kind == "pdf":
        return pdf_response(filename, fieldnames, rows, currency_code=currency_code)
    if kind == "xlsx":
        return xlsx_response(filename, fieldnames, rows, currency_code=currency_code)
    return csv_response(
        filename,
        fieldnames,
        rows,
        excel=kind == "xls",
        currency_code=currency_code,
    )


def xlsx_response(
    filename: str,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
    *,
    currency_code: str | None = None,
) -> Response:
    from app.common.imex.parser import write_xlsx

    header = list(fieldnames)
    body = [[csv_cell(row.get(key), key) for key in fieldnames] for row in rows]
    if currency_code:
        header = ["currency", *header]
        body = [[currency_code, *row] for row in body]
    download_name = filename.rsplit(".", 1)[0] + ".xlsx"
    return Response(
        content=write_xlsx(header, body),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


def pdf_response(
    filename: str,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
    *,
    currency_code: str | None = None,
) -> Response:
    lines = []
    if currency_code:
        lines.append(f"Monetary amounts in {currency_code}")
    lines.append(" | ".join(fieldnames))
    for row in rows:
        lines.append(" | ".join(csv_cell(row.get(key), key) for key in fieldnames))
    download_name = filename.rsplit(".", 1)[0] + ".pdf"
    return Response(
        content=simple_pdf(lines),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


def simple_pdf(lines: list[str]) -> bytes:
    """Minimal single-font PDF so report exports do not need another library."""

    escaped = [_pdf_escape(line[:200]) for line in lines] or [""]
    commands = ["BT", "/F1 9 Tf", "40 800 Td", "14 TL"]
    for index, line in enumerate(escaped):
        if index and index % 50 == 0:
            commands.append("ET")
            commands.append("BT")
            commands.append("/F1 9 Tf")
            commands.append("40 800 Td")
            commands.append("14 TL")
        commands.append(f"({line}) Tj")
        commands.append("T*")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", errors="replace")
    objects = [
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        b"2 0 obj<< /Type /Pages /Count 1 /Kids [3 0 R] >>endobj\n",
        (
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
        ),
        (
            b"4 0 obj<< /Length "
            + str(len(stream)).encode()
            + b" >>stream\n"
            + stream
            + b"\nendstream\nendobj\n"
        ),
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(content))
        content.extend(obj)
    xref = len(content)
    content.extend(f"xref\n0 {len(offsets)}\n".encode())
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(
        (f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    )
    return bytes(content)


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _format_decimal_cell(value: object, kind: CsvFieldClass) -> str | None:
    parsed = _as_decimal(value)
    if parsed is None:
        return None
    if kind == "quantity":
        return format_quantity_display(parsed)
    return format_money_display(parsed)


def _as_decimal(value: object) -> Decimal | None:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return Decimal(stripped)
        except InvalidOperation:
            return None
    return None
