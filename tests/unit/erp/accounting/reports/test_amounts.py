"""Unit tests for report amount conversion helpers."""

from decimal import Decimal
from types import SimpleNamespace

from app.erp.accounting.reports.amounts import document_base_net_tax


def test_document_base_net_tax_uses_post_discount_net() -> None:
    doc = SimpleNamespace(
        subtotal=Decimal("100.0000"),
        discount_amount=Decimal("10.0000"),
        tax_amount=Decimal("4.5000"),
        grand_total=Decimal("94.5000"),
        exchange_rate=Decimal("1"),
        base_amount=Decimal("94.5000"),
    )
    net, tax, grand = document_base_net_tax(doc)
    assert net == Decimal("90.0000")
    assert tax == Decimal("4.5000")
    assert grand == Decimal("94.5000")
