"""As-of open-item balance reconstruction."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.core.enums import OpenItemType, PartyType
from app.db.session import async_session_factory
from app.erp.accounting.integrity.service import _subledger_net
from app.erp.accounting.open_items.as_of import AsOfOpenItem, as_of_balances
from app.erp.accounting.open_items.schemas import OpenItemRow
from tests.api.erp.customer_payments.test_routes import _enable_books, _post_receipt
from tests.api.erp.quotation.test_routes import _create_customer, _create_product, _seeded_ids
from tests.conftest import login_headers, provision_admin


def test_as_of_open_item_maps_to_open_item_row() -> None:
    party_id = uuid4()
    doc_id = uuid4()
    currency_id = uuid4()
    item = AsOfOpenItem(
        party_id=party_id,
        item_type=OpenItemType.SALES_INVOICE,
        document_id=doc_id,
        document_number="SI-0001",
        document_date=date(2026, 1, 15),
        due_date=date(2026, 2, 15),
        currency_id=currency_id,
        original_amount=Decimal("100.0000"),
        balance=Decimal("40.0000"),
        is_debit=True,
        exchange_rate=Decimal("1.000000"),
    )
    row = item.to_open_item_row()
    assert isinstance(row, OpenItemRow)
    assert row.balance == Decimal("40.0000")
    assert row.base_balance == Decimal("40.0000")


def test_subledger_net_offsets_credits_against_invoices() -> None:
    party_id = uuid4()
    currency_id = uuid4()
    invoice = AsOfOpenItem(
        party_id=party_id,
        item_type=OpenItemType.SALES_INVOICE,
        document_id=uuid4(),
        document_number="SI-0001",
        document_date=date(2026, 1, 1),
        due_date=date(2026, 1, 31),
        currency_id=currency_id,
        original_amount=Decimal("100.0000"),
        balance=Decimal("100.0000"),
        is_debit=True,
        exchange_rate=Decimal("1.000000"),
    )
    advance = AsOfOpenItem(
        party_id=party_id,
        item_type=OpenItemType.CUSTOMER_PAYMENT,
        document_id=uuid4(),
        document_number="RCPT-0001",
        document_date=date(2026, 1, 10),
        due_date=None,
        currency_id=currency_id,
        original_amount=Decimal("30.0000"),
        balance=Decimal("30.0000"),
        is_debit=False,
        exchange_rate=Decimal("1.000000"),
    )
    assert _subledger_net([invoice, advance], party_type=PartyType.CUSTOMER) == Decimal("70.0000")


async def _accounts(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert roles.status_code == 200, roles.text
    by_role = {item["role"]: item["account_id"] for item in roles.json()["data"]}
    return {
        "BANK": by_role["BANK"],
        "ACCOUNTS_RECEIVABLE": by_role["ACCOUNTS_RECEIVABLE"],
        "ADVANCE_FROM_CUSTOMER": by_role["ADVANCE_FROM_CUSTOMER"],
    }


async def _posted_invoice(client: AsyncClient, headers: dict[str, str]) -> dict[str, object]:
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids, selling_rate="100.0000")
    created = await client.post(
        "/api/v1/sales-invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "currency_id": ids["aed"],
            "lines": [{"product_id": product_id, "quantity": "1"}],
        },
    )
    assert created.status_code == 201, created.text
    invoice = created.json()["data"]
    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers={**headers, "If-Match": str(invoice["version"]), "Idempotency-Key": uuid4().hex},
    )
    assert posted.status_code == 200, posted.text
    return posted.json()["data"]


@pytest.mark.asyncio
async def test_as_of_balances_excludes_later_payments(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    accounts = await _accounts(client, headers)
    invoice = await _posted_invoice(client, headers)
    invoice_id = UUID(str(invoice["id"]))
    total = Decimal(str(invoice["grand_total"]))
    today = date.today()
    before_payment = today - timedelta(days=1)

    async with async_session_factory() as session:
        rows_today = await as_of_balances(session, tenant_id, PartyType.CUSTOMER, today)
        open_today = next(
            row
            for row in rows_today
            if row.item_type == OpenItemType.SALES_INVOICE and row.document_id == invoice_id
        )
        assert open_today.balance == total

    allocated = (total / 2).quantize(Decimal("0.0001"))
    await _post_receipt(
        client,
        headers,
        {
            "customer_id": invoice["customer_id"],
            "amount_received": str(total),
            "payment_account_id": accounts["BANK"],
            "allocations": [
                {
                    "item_type": "SALES_INVOICE",
                    "item_id": str(invoice_id),
                    "amount": str(allocated),
                }
            ],
        },
    )

    async with async_session_factory() as session:
        rows_after = await as_of_balances(session, tenant_id, PartyType.CUSTOMER, today)
        open_after = next(
            row
            for row in rows_after
            if row.item_type == OpenItemType.SALES_INVOICE and row.document_id == invoice_id
        )
        assert open_after.balance == total - allocated

        rows_before = await as_of_balances(session, tenant_id, PartyType.CUSTOMER, before_payment)
        historical = next(
            (
                row
                for row in rows_before
                if row.item_type == OpenItemType.SALES_INVOICE and row.document_id == invoice_id
            ),
            None,
        )
        assert historical is None
