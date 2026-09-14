"""Unit tests for report CSV 2dp display formatting."""

import csv
import io
from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.erp.accounting.reports.csv_export import (
    csv_cell,
    csv_field_class,
    csv_response,
    rows_from_models,
)


class _SampleLine(BaseModel):
    layer_id: UUID
    sku: str
    qty_remaining: Decimal
    stock_value: Decimal
    landed_unit_cost: Decimal
    days: int
    exchange_rate: Decimal
    overdue: bool
    document_date: date


def test_csv_field_class_separates_money_qty_fx_and_integers() -> None:
    assert csv_field_class("stock_value") == "money"
    assert csv_field_class("grand_total") == "money"
    assert csv_field_class("days_1_30") == "money"
    assert csv_field_class("qty_remaining") == "quantity"
    assert csv_field_class("reorder_level") == "quantity"
    assert csv_field_class("tax_rate") == "percent"
    assert csv_field_class("exchange_rate") == "other"
    assert csv_field_class("days") == "other"
    assert csv_field_class("window_days") == "other"
    assert csv_field_class("sku") == "other"


def test_csv_cell_formats_money_and_qty_to_two_places() -> None:
    assert csv_cell(Decimal("4.000000"), "qty_remaining") == "4.00"
    assert csv_cell("320.0000", "stock_value") == "320.00"
    assert csv_cell(Decimal("80.555"), "landed_unit_cost") == "80.56"
    assert csv_cell(Decimal("5.5"), "tax_rate") == "5.50"


def test_csv_cell_leaves_fx_integers_ids_and_bools_unpadded() -> None:
    layer_id = UUID("12345678-1234-5678-1234-567812345678")
    assert csv_cell(Decimal("3.672500"), "exchange_rate") == "3.672500"
    assert csv_cell(5, "days") == "5"
    assert csv_cell(layer_id, "layer_id") == str(layer_id)
    assert csv_cell(True, "overdue") == "True"
    assert csv_cell(date(2026, 9, 14), "document_date") == "2026-09-14"
    assert csv_cell(None, "stock_value") == ""


def test_csv_response_applies_display_scale_by_field() -> None:
    line = _SampleLine(
        layer_id=UUID("12345678-1234-5678-1234-567812345678"),
        sku="PIPE-1",
        qty_remaining=Decimal("4.000000"),
        stock_value=Decimal("320.0000"),
        landed_unit_cost=Decimal("80.0000"),
        days=12,
        exchange_rate=Decimal("3.672500"),
        overdue=False,
        document_date=date(2026, 9, 14),
    )
    fields, rows = rows_from_models([line])
    response = csv_response("stock-valuation.csv", fields, rows)
    body = response.body.decode()
    parsed = list(csv.DictReader(io.StringIO(body)))
    assert parsed[0]["qty_remaining"] == "4.00"
    assert parsed[0]["stock_value"] == "320.00"
    assert parsed[0]["landed_unit_cost"] == "80.00"
    assert parsed[0]["exchange_rate"] == "3.672500"
    assert parsed[0]["days"] == "12"
    assert parsed[0]["overdue"] == "False"
    assert parsed[0]["sku"] == "PIPE-1"
