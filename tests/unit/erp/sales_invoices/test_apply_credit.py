"""Unit tests for sales invoice credit application."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import ValidationError
from app.erp.sales_invoices.service import SalesInvoiceService


@pytest.mark.asyncio
async def test_apply_credit_rejects_negative_credited_total() -> None:
    service = SalesInvoiceService.__new__(SalesInvoiceService)
    invoice_id = uuid4()
    tenant_id = uuid4()
    row = SimpleNamespace(
        amount_credited=Decimal("10.0000"),
        amount_paid=Decimal("0.0000"),
        amount_written_off=Decimal("0.0000"),
        grand_total=Decimal("100.0000"),
        balance_due=Decimal("90.0000"),
        payment_status="UNPAID",
    )
    service._require = AsyncMock(return_value=row)
    service.session = SimpleNamespace(flush=AsyncMock())

    with pytest.raises(ValidationError, match="Credited amount cannot be negative"):
        await service.apply_credit(tenant_id, invoice_id, Decimal("-20.0000"))
