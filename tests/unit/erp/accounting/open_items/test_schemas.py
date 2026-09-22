"""Open-item base amounts stay nullable when no exchange rate exists."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.core.enums import OpenItemType
from app.erp.accounting.open_items.schemas import OpenItemRow


def test_open_item_base_fields_are_null_without_a_rate() -> None:
    row = OpenItemRow(
        item_type=OpenItemType.SALES_INVOICE,
        document_id=uuid4(),
        document_number="INV-1",
        document_date=date(2026, 1, 15),
        currency_id=uuid4(),
        original_amount=Decimal("100.0000"),
        balance=Decimal("40.0000"),
        is_debit=True,
        exchange_rate=None,
    )
    assert row.doc_amount == Decimal("100.0000")
    assert row.base_amount is None
    assert row.base_balance is None


def test_open_item_base_fields_use_stored_rate() -> None:
    row = OpenItemRow(
        item_type=OpenItemType.SALES_INVOICE,
        document_id=uuid4(),
        document_number="INV-2",
        document_date=date(2026, 1, 15),
        currency_id=uuid4(),
        original_amount=Decimal("100.0000"),
        balance=Decimal("40.0000"),
        is_debit=True,
        exchange_rate=Decimal("3.6725"),
    )
    assert row.base_amount == Decimal("367.2500")
    assert row.base_balance == Decimal("146.9000")
