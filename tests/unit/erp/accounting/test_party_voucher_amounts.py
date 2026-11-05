"""Regression tests for party statement voucher debit/credit rules."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.core.enums import PartyType, VoucherType
from app.erp.accounting.reports.service import ReportService

_ZERO = Decimal("0")


def _voucher(
    *,
    voucher_type: VoucherType,
    party_id=None,
    party_type=None,
    total_amount="100.0000",
    exchange_rate="1",
    lines=None,
):
    return SimpleNamespace(
        voucher_type=voucher_type.value,
        party_id=party_id,
        party_type=party_type,
        total_amount=Decimal(total_amount),
        exchange_rate=Decimal(exchange_rate),
        lines=lines or [],
        reference=None,
        narration=None,
    )


def test_supplier_bank_payment_debits_header_amount() -> None:
    party_id = uuid4()
    row = _voucher(
        voucher_type=VoucherType.BANK_PAYMENT,
        party_id=party_id,
        party_type=PartyType.SUPPLIER.value,
    )
    debit, credit, _ = ReportService._party_voucher_amounts(
        row,
        party_type=PartyType.SUPPLIER,
        party_id=party_id,
        party_type_value=PartyType.SUPPLIER.value,
    )
    assert debit == Decimal("100.0000")
    assert credit == _ZERO


def test_supplier_journal_uses_line_amounts() -> None:
    party_id = uuid4()
    other_id = uuid4()
    row = _voucher(
        voucher_type=VoucherType.JOURNAL,
        party_id=other_id,
        party_type=PartyType.SUPPLIER.value,
        lines=[
            SimpleNamespace(
                party_id=party_id,
                party_type=PartyType.SUPPLIER.value,
                debit=Decimal("0"),
                credit=Decimal("25.0000"),
                description="AP line",
            )
        ],
    )
    debit, credit, description = ReportService._party_voucher_amounts(
        row,
        party_type=PartyType.SUPPLIER,
        party_id=party_id,
        party_type_value=PartyType.SUPPLIER.value,
    )
    assert debit == _ZERO
    assert credit == Decimal("25.0000")
    assert description == "AP line"


def test_supplier_journal_header_only_credits() -> None:
    party_id = uuid4()
    row = _voucher(
        voucher_type=VoucherType.JOURNAL,
        party_id=party_id,
        party_type=PartyType.SUPPLIER.value,
        lines=[],
    )
    debit, credit, _ = ReportService._party_voucher_amounts(
        row,
        party_type=PartyType.SUPPLIER,
        party_id=party_id,
        party_type_value=PartyType.SUPPLIER.value,
    )
    assert debit == _ZERO
    assert credit == Decimal("100.0000")


def test_unrelated_voucher_yields_zero() -> None:
    party_id = uuid4()
    row = _voucher(
        voucher_type=VoucherType.BANK_PAYMENT,
        party_id=uuid4(),
        party_type=PartyType.SUPPLIER.value,
    )
    debit, credit, _ = ReportService._party_voucher_amounts(
        row,
        party_type=PartyType.SUPPLIER,
        party_id=party_id,
        party_type_value=PartyType.SUPPLIER.value,
    )
    assert debit == _ZERO
    assert credit == _ZERO
