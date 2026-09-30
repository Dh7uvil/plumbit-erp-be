"""Invoice settlement guards."""

from __future__ import annotations

from decimal import Decimal

from app.common.utils.currency import quantize_money
from app.core.exceptions import PaymentOverAllocatedError

_ZERO = Decimal("0")


def invoice_settled_amount(
    *,
    amount_paid: Decimal,
    amount_credited: Decimal,
    amount_written_off: Decimal,
) -> Decimal:
    return quantize_money(amount_paid + amount_credited + amount_written_off)


def assert_invoice_not_over_settled(
    *,
    grand_total: Decimal,
    amount_paid: Decimal,
    amount_credited: Decimal,
    amount_written_off: Decimal,
) -> None:
    settled = invoice_settled_amount(
        amount_paid=amount_paid,
        amount_credited=amount_credited,
        amount_written_off=amount_written_off,
    )
    if settled > grand_total:
        raise PaymentOverAllocatedError(
            details={
                "grand_total": str(grand_total),
                "amount_paid": str(amount_paid),
                "amount_credited": str(amount_credited),
                "amount_written_off": str(amount_written_off),
            }
        )
