"""VAT register per-line category tests."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.core.enums import TaxCategory
from app.erp.accounting.reports.tax_registers import TaxRegisters


class _Line:
    def __init__(self, *, tax_id, amount: Decimal, tax_amount: Decimal) -> None:
        self.tax_id = tax_id
        self.amount = amount
        self.tax_amount = tax_amount


class _Doc:
    def __init__(self, lines: list[_Line]) -> None:
        self.id = uuid4()
        self.subtotal = sum((line.amount for line in lines), Decimal("0"))
        self.discount_amount = Decimal("0")
        self.tax_amount = sum((line.tax_amount for line in lines), Decimal("0"))
        self.grand_total = self.subtotal + self.tax_amount
        self.exchange_rate = Decimal("1")
        self.base_amount = self.grand_total
        self.lines = lines


def test_document_register_lines_split_mixed_tax_categories() -> None:
    standard_tax_id = uuid4()
    zero_tax_id = uuid4()
    taxes = {
        standard_tax_id: SimpleNamespace(tax_category=TaxCategory.STANDARD.value),
        zero_tax_id: SimpleNamespace(tax_category=TaxCategory.ZERO_RATED.value),
    }
    doc = _Doc(
        [
            _Line(tax_id=standard_tax_id, amount=Decimal("100"), tax_amount=Decimal("5")),
            _Line(tax_id=zero_tax_id, amount=Decimal("50"), tax_amount=Decimal("0")),
        ]
    )
    rows = TaxRegisters._document_register_lines(
        TaxRegisters(),
        doc,
        document_type="SALES_INVOICE",
        document_number="SI-1",
        document_date=date(2026, 1, 15),
        party_id=uuid4(),
        party_name="Customer",
        party_trn=None,
        tax_treatment="REGISTERED",
        place_of_supply="DUBAI",
        taxes=taxes,
        sign=Decimal("1"),
    )
    categories = {row.tax_category for row in rows}
    assert categories == {TaxCategory.STANDARD.value, TaxCategory.ZERO_RATED.value}
