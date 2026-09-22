"""API tests for the per-record activity feed."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.integrations.storage.client import get_storage
from tests.api.common.attachments.test_attachment_isolation import FakeS3Client, _upload
from tests.api.erp.quotation.test_routes import (
    _create_customer,
    _create_product,
    _create_quote,
    _if_match,
    _seeded_ids,
)
from tests.api.inventory_management.stock.test_stock_routes import _user_headers
from tests.conftest import login_headers, provision_admin


@pytest.fixture
def fake_s3(app):
    from app.integrations.storage.client import S3Storage

    client = FakeS3Client()
    storage = S3Storage(client, bucket="test-bucket", presign_ttl_seconds=60)
    app.dependency_overrides[get_storage] = lambda: storage
    yield client
    app.dependency_overrides.pop(get_storage, None)


@pytest.mark.asyncio
async def test_quotation_activity_requires_quotation_read(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    quote_id = created["body"]["data"]["id"]

    reader = await _user_headers(client, headers, tenant_id, codes=("sales.quotation.read",))
    listed = await client.get(
        "/api/v1/activity",
        headers=reader,
        params={"entity_type": "quotation", "entity_id": quote_id},
    )
    assert listed.status_code == 200, listed.text
    actions = {item["action"] for item in listed.json()["data"]}
    assert "CREATE" in actions
    assert all("password" not in str(item.get("changed_fields")) for item in listed.json()["data"])

    customer_only = await _user_headers(client, headers, tenant_id, codes=("crm.customer.read",))
    denied = await client.get(
        "/api/v1/activity",
        headers=customer_only,
        params={"entity_type": "quotation", "entity_id": quote_id},
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_activity_unregistered_entity_type_is_validation_error(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.get(
        "/api/v1/activity",
        headers=headers,
        params={"entity_type": "lead_source", "entity_id": str(uuid4())},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_activity_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    ids = await _seeded_ids(client, headers_a)
    customer_id = await _create_customer(client, headers_a)
    product_id = await _create_product(client, headers_a, ids)
    created = await _create_quote(client, headers_a, customer_id=customer_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    quote_id = created["body"]["data"]["id"]

    listed = await client.get(
        "/api/v1/activity",
        headers=headers_b,
        params={"entity_type": "quotation", "entity_id": quote_id},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"] == []
    assert listed.json()["meta"]["total"] == 0


async def _list_quote_activity(
    client: AsyncClient,
    headers: dict[str, str],
    quote_id: str,
) -> list[dict[str, object]]:
    listed = await client.get(
        "/api/v1/activity",
        headers=headers,
        params={"entity_type": "quotation", "entity_id": quote_id, "page_size": 100},
    )
    assert listed.status_code == 200, listed.text
    return listed.json()["data"]


@pytest.mark.asyncio
async def test_quotation_activity_includes_actor_email_and_edit_kind(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    quote_id = created["body"]["data"]["id"]

    rows = await _list_quote_activity(client, headers, quote_id)
    create_row = next(item for item in rows if item["action"] == "CREATE")
    assert create_row["kind"] == "edit"
    assert create_row["actor_email"] == email
    assert create_row["actor_id"]
    assert create_row["actor_name"]


@pytest.mark.asyncio
async def test_quotation_submit_approve_reject_are_approval_kind(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    quote_id = created["body"]["data"]["id"]
    version = created["body"]["data"]["version"]

    submitted = await client.post(
        f"/api/v1/quotations/{quote_id}/submit",
        headers=_if_match(headers, version),
    )
    assert submitted.status_code == 200, submitted.text
    rejected = await client.post(
        f"/api/v1/quotations/{quote_id}/reject",
        headers=_if_match(headers, submitted.json()["data"]["version"]),
        json={"reason": "Pricing too high"},
    )
    assert rejected.status_code == 200, rejected.text

    rows = await _list_quote_activity(client, headers, quote_id)
    by_action = {item["action"]: item for item in rows}
    assert by_action["SUBMIT"]["kind"] == "approval"
    assert by_action["REJECT"]["kind"] == "approval"
    assert by_action["REJECT"]["summary"] == "Pricing too high"
    reason_fields = [
        change
        for change in by_action["REJECT"]["changed_fields"]
        if change["field"] == "reason"
    ]
    assert reason_fields
    assert reason_fields[0]["new_value"] == "Pricing too high"

    approved_quote = await _create_quote(
        client, headers, customer_id=customer_id, product_id=product_id
    )
    approved_id = approved_quote["body"]["data"]["id"]
    submitted_ok = await client.post(
        f"/api/v1/quotations/{approved_id}/submit",
        headers=_if_match(headers, approved_quote["body"]["data"]["version"]),
    )
    assert submitted_ok.status_code == 200, submitted_ok.text
    approved = await client.post(
        f"/api/v1/quotations/{approved_id}/approve",
        headers=_if_match(headers, submitted_ok.json()["data"]["version"]),
    )
    assert approved.status_code == 200, approved.text
    approved_rows = await _list_quote_activity(client, headers, approved_id)
    assert next(item for item in approved_rows if item["action"] == "APPROVE")["kind"] == (
        "approval"
    )


@pytest.mark.asyncio
async def test_attachment_upload_appears_on_parent_activity(
    client: AsyncClient, fake_s3: Any
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_quote(client, headers, customer_id=customer_id, product_id=product_id)
    assert created["status_code"] == 201, created["text"]
    quote_id = created["body"]["data"]["id"]

    uploaded = await _upload(
        client,
        headers,
        entity_type="QUOTATION",
        entity_id=quote_id,
        filename="packing-list.json",
    )
    assert uploaded.status_code == 201, uploaded.text
    assert fake_s3.objects

    rows = await _list_quote_activity(client, headers, quote_id)
    attachment_rows = [item for item in rows if item["kind"] == "attachment"]
    assert len(attachment_rows) == 1
    assert attachment_rows[0]["action"] == "CREATE"
    assert attachment_rows[0]["summary"] == "packing-list.json"
    assert attachment_rows[0]["actor_email"] == email
