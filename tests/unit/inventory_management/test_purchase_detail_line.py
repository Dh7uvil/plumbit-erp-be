"""Purchase-detail line mapping for the item inquiry tabs."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.inventory_management.history.service import purchase_detail_line


def _row(**overrides: object) -> dict[str, object]:
    line_id = uuid4()
    document_id = uuid4()
    product_id = uuid4()
    party_id = uuid4()
    row: dict[str, object] = {
        "line_id": line_id,
        "document_id": document_id,
        "document_number": "BILL-1",
        "document_date": date(2026, 9, 21),
        "product_id": product_id,
        "description": "Extension nipple",
        "party_id": party_id,
        "party_name": "Aagman International",
        "quantity": Decimal("10000"),
        "rate": Decimal("22"),
        "amount": Decimal("220000"),
        "currency_code": "USD",
        "warehouse_id": None,
        "warehouse_name": None,
        "supplier_invoice_number": None,
        "lc_date": None,
        "lc_number": None,
        "exchange_rate": Decimal("3.673500"),
        "is_posted": True,
        "branch_id": None,
        "branch_name": None,
    }
    row.update(overrides)
    return row


def test_foreign_bill_keeps_document_currency_and_converts_local_amounts() -> None:
    line = purchase_detail_line(_row())
    assert line.rate == Decimal("22")
    assert line.amount == Decimal("220000")
    assert line.currency_code == "USD"
    assert line.fc_rate == Decimal("22")
    assert line.rate_lcy == Decimal("80.8170")
    assert line.amount_lcy == Decimal("808170.0000")
    assert line.lc_date is None


def test_import_letter_of_credit_uses_only_the_import_document() -> None:
    line = purchase_detail_line(
        _row(
            lc_number="LC-44",
            lc_date=date(2026, 8, 1),
            currency_code="USD",
            rate=Decimal("0.2"),
            amount=Decimal("200"),
        )
    )
    assert line.lc_number == "LC-44"
    assert line.lc_date == date(2026, 8, 1)
    assert line.rate_lcy == Decimal("0.7347")
    assert line.amount_lcy == Decimal("734.7000")
