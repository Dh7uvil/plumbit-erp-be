"""Dunning rules and payment reminder API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.quotation.test_routes import _create_customer, _seeded_ids
from tests.api.erp.sales_orders.test_routes import _create_product
from tests.conftest import login_headers, provision_admin


def _idempotent(headers: dict[str, str], version: object) -> dict[str, str]:
    return {**headers, "If-Match": str(version), "Idempotency-Key": uuid4().hex}


async def _customer_with_email(client: AsyncClient, headers: dict[str, str]) -> str:
    customer_id = await _create_customer(client, headers)
    created = await client.post(
        "/api/v1/contacts",
        headers=headers,
        json={
            "customer_id": customer_id,
            "name": "Billing Contact",
            "email": "billing@example.com",
            "is_primary": True,
        },
    )
    assert created.status_code == 201, created.text
    return customer_id


async def _posted_invoice_with_balance(
    client: AsyncClient, headers: dict[str, str]
) -> dict[str, object]:
    today = datetime.now(UTC).date().isoformat()
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"books_start_date": today},
    )
    assert updated.status_code == 200, updated.text
    ids = await _seeded_ids(client, headers)
    customer_id = await _customer_with_email(client, headers)
    product_id = await _create_product(client, headers, ids)
    terms = await client.get("/api/v1/payment-terms?page_size=10", headers=headers)
    assert terms.status_code == 200, terms.text
    payment_terms_id = terms.json()["data"][0]["id"]
    created = await client.post(
        "/api/v1/sales-invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "payment_terms_id": payment_terms_id,
            "lines": [{"product_id": product_id, "quantity": "1"}],
        },
    )
    assert created.status_code == 201, created.text
    invoice = created.json()["data"]
    posted = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/post",
        headers=_idempotent(headers, invoice["version"]),
    )
    assert posted.status_code == 200, posted.text
    return posted.json()["data"]


@pytest.mark.asyncio
async def test_dunning_rule_crud_and_send_reminder(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    rule = await client.post(
        "/api/v1/dunning-rules",
        headers=headers,
        json={
            "name": f"7 days overdue {uuid4().hex[:8]}",
            "days_offset": 7,
            "template_key": "PAYMENT_OVERDUE",
            "escalate": False,
        },
    )
    assert rule.status_code == 201, rule.text
    rule_id = rule.json()["data"]["id"]

    listed = await client.get("/api/v1/dunning-rules", headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(row["id"] == rule_id for row in listed.json()["data"])

    invoice = await _posted_invoice_with_balance(client, headers)
    assert invoice["due_date"] is not None
    assert "send_reminder" in invoice["available_actions"]

    sent = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/send-reminder",
        headers=headers,
        json={"dunning_rule_id": rule_id},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["data"]["recipient_email"] == "billing@example.com"

    history = await client.get(
        f"/api/v1/sales-invoices/{invoice['id']}/payment-reminders",
        headers=headers,
    )
    assert history.status_code == 200, history.text
    logs = history.json()["data"]
    assert len(logs) == 1
    assert logs[0]["dunning_rule_id"] == rule_id

    duplicate = await client.post(
        f"/api/v1/sales-invoices/{invoice['id']}/send-reminder",
        headers=headers,
        json={"dunning_rule_id": rule_id},
    )
    assert duplicate.status_code == 409, duplicate.text

    deleted = await client.delete(f"/api/v1/dunning-rules/{rule_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
