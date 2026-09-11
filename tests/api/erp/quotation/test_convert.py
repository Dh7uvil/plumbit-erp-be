"""API tests for quotation-to-sales-order conversion."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.quotation.test_routes import (
    _create_customer,
    _create_product,
    _create_quote,
    _if_match,
    _seeded_ids,
    _send_quote,
)
from tests.conftest import login_headers, provision_admin


def _convert_headers(
    headers: dict[str, str], version: object, *, key: str | None = None
) -> dict[str, str]:
    return {**_if_match(headers, version), "Idempotency-Key": key or str(uuid4())}


async def _accept_quote(
    client: AsyncClient, headers: dict[str, str], quote: dict[str, object]
) -> dict[str, object]:
    sent = await _send_quote(client, headers, quote)
    accepted = await client.post(
        f"/api/v1/quotations/{sent['id']}/accept",
        headers=_if_match(headers, sent["version"]),
    )
    assert accepted.status_code == 200, accepted.text
    return accepted.json()["data"]


@pytest.mark.asyncio
async def test_convert_accepted_quotation_copies_totals(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote = await _accept_quote(client, headers, created["body"]["data"])
    converted = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-sales-order",
        headers=_convert_headers(headers, quote["version"]),
    )
    assert converted.status_code == 200, converted.text
    order = converted.json()["data"]
    assert Decimal(order["subtotal"]) == Decimal(str(quote["subtotal"]))
    assert Decimal(order["tax_amount"]) == Decimal(str(quote["tax_amount"]))
    assert Decimal(order["grand_total"]) == Decimal(str(quote["grand_total"]))
    assert order["source_quotation_id"] == quote["id"]
    assert order["lines"][0]["source_quotation_line_id"] == quote["lines"][0]["id"]

    fetched = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    data = fetched.json()["data"]
    assert data["status"] == "CONVERTED"
    assert data["converted_document_id"] == order["id"]
    assert data["converted_document_type"] == "SALES_ORDER"


@pytest.mark.asyncio
async def test_convert_rejects_non_accepted_quotation(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    rejected = await client.post(
        f"/api/v1/quotations/{created['body']['data']['id']}/convert-to-sales-order",
        headers=_convert_headers(headers, created["body"]["data"]["version"]),
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


@pytest.mark.asyncio
async def test_second_convert_is_rejected(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote = await _accept_quote(client, headers, created["body"]["data"])
    first = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-sales-order",
        headers=_convert_headers(headers, quote["version"]),
    )
    assert first.status_code == 200, first.text
    quotation = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    second = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-sales-order",
        headers=_convert_headers(headers, quotation.json()["data"]["version"]),
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


@pytest.mark.asyncio
async def test_convert_failure_leaves_quotation_accepted(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote = await _accept_quote(client, headers, created["body"]["data"])

    async def boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("allocate failed")

    monkeypatch.setattr(
        "app.erp.accounting.service.DocumentSequenceService.allocate",
        boom,
    )
    with pytest.raises(RuntimeError, match="allocate failed"):
        await client.post(
            f"/api/v1/quotations/{quote['id']}/convert-to-sales-order",
            headers=_convert_headers(headers, quote["version"]),
        )
    fetched = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    data = fetched.json()["data"]
    assert data["status"] == "ACCEPTED"
    assert data["converted_document_id"] is None


@pytest.mark.asyncio
async def test_convert_requires_sales_order_create(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote = await _accept_quote(client, headers, created["body"]["data"])
    permissions = await client.get("/api/v1/permissions?module=erp&page_size=100", headers=headers)
    codes = {item["code"]: item["id"] for item in permissions.json()["data"]}
    suffix = uuid4().hex[:8]
    role = await client.post(
        "/api/v1/roles",
        headers=headers,
        json={
            "name": f"Quote updater {suffix}",
            "permission_ids": [
                codes["sales.quotation.read"],
                codes["sales.quotation.update"],
            ],
        },
    )
    assert role.status_code == 201, role.text
    limited_email = f"updater-{suffix}@example.com"
    user = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Quote Updater",
            "email": limited_email,
            "password": "password12",
            "role_ids": [role.json()["data"]["id"]],
        },
    )
    assert user.status_code == 201, user.text
    limited_headers = await login_headers(client, tenant_id, limited_email, "password12")
    denied = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-sales-order",
        headers=_convert_headers(limited_headers, quote["version"]),
    )
    assert denied.status_code == 403
    fetched = await client.get(f"/api/v1/quotations/{quote['id']}", headers=limited_headers)
    assert "convert" not in fetched.json()["data"]["available_actions"]


@pytest.mark.asyncio
async def test_partial_convert_then_remainder_marks_converted(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    quote = await _accept_quote(client, headers, created["body"]["data"])
    line_id = quote["lines"][0]["id"]
    first = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-sales-order",
        headers=_convert_headers(headers, quote["version"]),
        json={"lines": [{"source_line_id": line_id, "quantity": "1"}]},
    )
    assert first.status_code == 200, first.text
    assert Decimal(first.json()["data"]["lines"][0]["quantity"]) == Decimal("1")

    fetched = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    data = fetched.json()["data"]
    assert data["status"] == "PARTIALLY_CONVERTED"
    assert Decimal(data["lines"][0]["qty_converted"]) == Decimal("1")
    assert Decimal(data["lines"][0]["qty_remaining"]) == Decimal("1")
    related_types = {item["document_type"] for item in data["related_documents"]}
    assert "SALES_ORDER" in related_types
    assert "create_sales_invoice" in data["available_actions"]

    second = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-sales-order",
        headers=_convert_headers(headers, data["version"]),
    )
    assert second.status_code == 200, second.text
    converted = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    assert converted.json()["data"]["status"] == "CONVERTED"
    assert converted.json()["data"]["converted_document_id"] == second.json()["data"]["id"]


@pytest.mark.asyncio
async def test_convert_to_sales_invoice_and_over_conversion(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(
        client, headers, customer_id=customer_id, product_id=product_id, quantity="2"
    )
    quote = await _accept_quote(client, headers, created["body"]["data"])
    line_id = quote["lines"][0]["id"]
    exceeded = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-sales-invoice",
        headers=_convert_headers(headers, quote["version"]),
        json={"lines": [{"source_line_id": line_id, "quantity": "5"}]},
    )
    assert exceeded.status_code == 422, exceeded.text
    assert exceeded.json()["error"]["code"] == "VALIDATION_ERROR"

    converted = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-sales-invoice",
        headers=_convert_headers(headers, quote["version"]),
    )
    assert converted.status_code == 200, converted.text
    invoice = converted.json()["data"]
    assert invoice["status"] == "DRAFT"
    assert invoice["source_quotation_id"] == quote["id"]
    assert invoice["lines"][0]["source_quotation_line_id"] == line_id
    assert invoice["journal_entry_id"] is None
    assert Decimal(invoice["grand_total"]) == Decimal(str(quote["grand_total"]))

    fetched = await client.get(f"/api/v1/quotations/{quote['id']}", headers=headers)
    data = fetched.json()["data"]
    assert data["status"] == "CONVERTED"
    assert data["converted_document_type"] == "SALES_INVOICE"
    assert data["converted_document_id"] == invoice["id"]
    assert any(
        item["document_type"] == "SALES_INVOICE" and item["document_id"] == invoice["id"]
        for item in data["related_documents"]
    )

    detail = await client.get(f"/api/v1/sales-invoices/{invoice['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    related = detail.json()["data"]["related_documents"]
    assert any(item["document_type"] == "QUOTATION" for item in related)
    assert detail.json()["data"]["is_overdue"] is False
    assert detail.json()["data"]["is_partially_credited"] is False
