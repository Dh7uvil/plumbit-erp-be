"""API tests for period lock GET, preview, PATCH, and stock enforcement."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.quotation.test_routes import (
    _create_customer,
    _create_quote,
    _seeded_ids,
)
from tests.api.erp.quotation.test_routes import (
    _create_product as _create_quote_product,
)
from tests.api.inventory_management.stock.test_stock_routes import (
    _STOCK_CLERK_CODES,
    _create_adjustment,
    _create_product,
    _if_match,
    _post_document,
    _seeded,
    _stock_clerk_headers,
    _user_headers,
)
from tests.conftest import login_headers, provision_admin

_UNLOCK_REASON = "Unlocking after completing the audit review"


async def _set_lock(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    lock_date: str | None = None,
    hard_lock_date: str | None = None,
    reason: str | None = None,
    acknowledge: bool = False,
    include_lock: bool = False,
    include_hard: bool = False,
) -> object:
    payload: dict[str, object] = {}
    if include_lock or lock_date is not None:
        payload["lock_date"] = lock_date
    if include_hard or hard_lock_date is not None:
        payload["hard_lock_date"] = hard_lock_date
    if reason is not None:
        payload["reason"] = reason
    if acknowledge:
        payload["acknowledge_negative_stock"] = True
    return await client.patch("/api/v1/period-lock", headers=headers, json=payload)


@pytest.mark.asyncio
async def test_get_period_lock_with_organization_read(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    response = await client.get("/api/v1/period-lock", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["lock_date"] is None
    assert data["hard_lock_date"] is None
    assert data["lock_reason"] is None
    assert data["hard_lock_reason"] is None


@pytest.mark.asyncio
async def test_preview_and_apply_lock(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    preview = await client.get("/api/v1/period-lock/preview?lock_date=2024-12-31", headers=headers)
    assert preview.status_code == 200, preview.text
    body = preview.json()["data"]
    assert body["blocked"] is False
    assert body["requires_acknowledgement"] is False
    assert body["negative_balances_are_current"] is True
    applied = await _set_lock(client, headers, lock_date="2024-12-31")
    assert applied.status_code == 200, applied.text
    assert applied.json()["data"]["lock_date"] == "2024-12-31"


@pytest.mark.asyncio
async def test_preview_includes_registered_drafts_not_unregistered_slices(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    today = date.today().isoformat()
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=product_id
    )
    assert created["status_code"] == 201, created["text"]
    adjustment_id = created["body"]["data"]["id"]

    quote_ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    quote_product = await _create_quote_product(client, headers, quote_ids)
    quoted = await _create_quote(client, headers, customer_id=customer_id, product_id=quote_product)
    assert quoted["status_code"] == 201, quoted["text"]

    preview = await client.get(f"/api/v1/period-lock/preview?lock_date={today}", headers=headers)
    assert preview.status_code == 200, preview.text
    docs = preview.json()["data"]["unposted_documents"]
    types = {item["document_type"] for item in docs}
    assert "stock_adjustment" in types
    assert any(item["id"] == adjustment_id for item in docs)
    assert "quotation" not in types


@pytest.mark.asyncio
async def test_override_posts_into_soft_lock_but_not_hard_lock(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await client.post(
        "/api/v1/stock-adjustments",
        headers=headers,
        json={
            "warehouse_id": ids["main"],
            "reason": "OPENING_STOCK",
            "document_date": "2020-01-15",
            "lines": [{"product_id": product_id, "qty_delta": "5"}],
        },
    )
    assert created.status_code == 201, created.text
    doc = created.json()["data"]
    locked = await _set_lock(client, headers, lock_date="2024-12-31")
    assert locked.status_code == 200, locked.text

    posted = await _post_document(
        client, headers, f"/api/v1/stock-adjustments/{doc['id']}/post", doc["version"]
    )
    assert posted.status_code == 200, posted.text

    hard = await client.post(
        "/api/v1/stock-adjustments",
        headers=headers,
        json={
            "warehouse_id": ids["main"],
            "reason": "OPENING_STOCK",
            "document_date": "2020-02-01",
            "lines": [{"product_id": product_id, "qty_delta": "1"}],
        },
    )
    assert hard.status_code == 201, hard.text
    hard_doc = hard.json()["data"]
    closed = await _set_lock(client, headers, hard_lock_date="2024-06-30")
    assert closed.status_code == 200, closed.text
    rejected = await _post_document(
        client,
        headers,
        f"/api/v1/stock-adjustments/{hard_doc['id']}/post",
        hard_doc["version"],
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["details"]["tier"] == "hard"


@pytest.mark.asyncio
async def test_create_into_locked_period_is_rejected(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    locked = await _set_lock(client, headers, lock_date="2024-12-31")
    assert locked.status_code == 200, locked.text
    clerk = await _stock_clerk_headers(client, headers, tenant_id)
    created = await client.post(
        "/api/v1/stock-adjustments",
        headers=clerk,
        json={
            "warehouse_id": ids["main"],
            "reason": "OPENING_STOCK",
            "document_date": "2020-01-15",
            "lines": [{"product_id": product_id, "qty_delta": "5"}],
        },
    )
    assert created.status_code == 409, created.text
    assert created.json()["error"]["code"] == "PERIOD_LOCKED"
    assert created.json()["error"]["details"]["tier"] == "soft"


@pytest.mark.asyncio
async def test_redate_stranded_draft_succeeds_in_place_edit_fails(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    clerk = await _stock_clerk_headers(client, headers, tenant_id)
    created = await client.post(
        "/api/v1/stock-adjustments",
        headers=clerk,
        json={
            "warehouse_id": ids["main"],
            "reason": "OPENING_STOCK",
            "document_date": "2020-01-15",
            "lines": [{"product_id": product_id, "qty_delta": "5"}],
        },
    )
    assert created.status_code == 201, created.text
    doc = created.json()["data"]
    locked = await _set_lock(client, headers, lock_date="2024-12-31")
    assert locked.status_code == 200, locked.text

    in_place = await client.patch(
        f"/api/v1/stock-adjustments/{doc['id']}",
        headers=_if_match(clerk, doc["version"]),
        json={"notes": "still locked", "version": doc["version"]},
    )
    assert in_place.status_code == 409, in_place.text
    assert in_place.json()["error"]["code"] == "PERIOD_LOCKED"

    today = date.today().isoformat()
    moved = await client.patch(
        f"/api/v1/stock-adjustments/{doc['id']}",
        headers=_if_match(clerk, doc["version"]),
        json={"document_date": today, "notes": "moved", "version": doc["version"]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["data"]["document_date"] == today
    assert moved.json()["data"]["period_locked"] is False


@pytest.mark.asyncio
async def test_delete_and_cancel_locked_dated_drafts(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    clerk = await _stock_clerk_headers(client, headers, tenant_id)
    to_delete = await client.post(
        "/api/v1/stock-adjustments",
        headers=clerk,
        json={
            "warehouse_id": ids["main"],
            "reason": "OPENING_STOCK",
            "document_date": "2020-01-15",
            "lines": [{"product_id": product_id, "qty_delta": "5"}],
        },
    )
    to_cancel = await client.post(
        "/api/v1/stock-adjustments",
        headers=clerk,
        json={
            "warehouse_id": ids["main"],
            "reason": "OPENING_STOCK",
            "document_date": "2020-01-16",
            "lines": [{"product_id": product_id, "qty_delta": "2"}],
        },
    )
    assert to_delete.status_code == 201, to_delete.text
    assert to_cancel.status_code == 201, to_cancel.text
    locked = await _set_lock(client, headers, lock_date="2024-12-31")
    assert locked.status_code == 200, locked.text

    deleted = await client.delete(
        f"/api/v1/stock-adjustments/{to_delete.json()['data']['id']}",
        headers=_if_match(clerk, to_delete.json()["data"]["version"]),
    )
    assert deleted.status_code == 200, deleted.text
    cancelled = await client.post(
        f"/api/v1/stock-adjustments/{to_cancel.json()['data']['id']}/cancel",
        headers=_if_match(clerk, to_cancel.json()["data"]["version"]),
        json={"reason": "Not needed", "version": to_cancel.json()["data"]["version"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_available_actions_drop_post_when_locked(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    clerk = await _stock_clerk_headers(client, headers, tenant_id)
    override = await _user_headers(
        client, headers, tenant_id, codes=_STOCK_CLERK_CODES + ("erp.period.override",)
    )
    created = await client.post(
        "/api/v1/stock-adjustments",
        headers=clerk,
        json={
            "warehouse_id": ids["main"],
            "reason": "OPENING_STOCK",
            "document_date": "2020-01-15",
            "lines": [{"product_id": product_id, "qty_delta": "5"}],
        },
    )
    assert created.status_code == 201, created.text
    doc_id = created.json()["data"]["id"]
    locked = await _set_lock(client, headers, lock_date="2024-12-31")
    assert locked.status_code == 200, locked.text

    clerk_view = await client.get(f"/api/v1/stock-adjustments/{doc_id}", headers=clerk)
    assert clerk_view.status_code == 200, clerk_view.text
    clerk_data = clerk_view.json()["data"]
    assert clerk_data["period_locked"] is True
    assert "post" not in clerk_data["available_actions"]
    assert "cancel" in clerk_data["available_actions"]
    assert "delete" in clerk_data["available_actions"]

    override_view = await client.get(f"/api/v1/stock-adjustments/{doc_id}", headers=override)
    assert override_view.status_code == 200, override_view.text
    override_data = override_view.json()["data"]
    assert override_data["period_locked"] is True
    assert "post" in override_data["available_actions"]


@pytest.mark.asyncio
async def test_quotation_create_ignores_period_lock(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded_ids(client, headers)
    customer_id = await _create_customer(client, headers)
    product_id = await _create_quote_product(client, headers, ids)
    locked = await _set_lock(client, headers, lock_date="2024-12-31")
    assert locked.status_code == 200, locked.text
    created = await client.post(
        "/api/v1/quotations",
        headers=headers,
        json={
            "customer_id": customer_id,
            "quote_date": "2020-01-15",
            "lines": [{"product_id": product_id, "quantity": "1"}],
        },
    )
    assert created.status_code == 201, created.text


@pytest.mark.asyncio
async def test_negative_stock_blocks_or_requires_acknowledge(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    toggled = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"allow_negative_stock": True},
    )
    assert toggled.status_code == 200, toggled.text
    created = await _create_adjustment(
        client,
        headers,
        warehouse_id=ids["main"],
        product_id=product_id,
        reason="DAMAGE",
        qty_delta="-4",
    )
    doc = created["body"]["data"]
    posted = await _post_document(
        client, headers, f"/api/v1/stock-adjustments/{doc['id']}/post", doc["version"]
    )
    assert posted.status_code == 200, posted.text

    preview = await client.get("/api/v1/period-lock/preview?lock_date=2024-12-31", headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["requires_acknowledgement"] is True
    assert preview.json()["data"]["blocked"] is False
    assert preview.json()["data"]["negative_balances_total_count"] == 1

    missing_ack = await _set_lock(client, headers, lock_date="2024-12-31")
    assert missing_ack.status_code == 409, missing_ack.text
    error = missing_ack.json()["error"]
    assert error["code"] == "PERIOD_LOCK_BLOCKED_NEGATIVE_STOCK"
    assert error["details"]["reason"] == "acknowledgement_required"
    assert error["details"]["balances"][0]["sku"]
    assert error["details"]["total_count"] == 1

    acknowledged = await _set_lock(client, headers, lock_date="2024-12-31", acknowledge=True)
    assert acknowledged.status_code == 200, acknowledged.text

    unlocked = await _set_lock(
        client, headers, lock_date=None, reason=_UNLOCK_REASON, include_lock=True
    )
    assert unlocked.status_code == 200, unlocked.text

    disallowed = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"allow_negative_stock": False},
    )
    assert disallowed.status_code == 200, disallowed.text
    blocked = await _set_lock(client, headers, lock_date="2024-12-31")
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["details"]["reason"] == "negative_stock_disallowed"
    still_acked = await _set_lock(client, headers, lock_date="2024-12-31", acknowledge=True)
    assert still_acked.status_code == 409, still_acked.text
    assert still_acked.json()["error"]["details"]["reason"] == "negative_stock_disallowed"


@pytest.mark.asyncio
async def test_lock_invariants_and_unlock_reason(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    future = (date.today() + timedelta(days=30)).isoformat()
    future_lock = await _set_lock(client, headers, lock_date=future)
    assert future_lock.status_code == 422, future_lock.text

    inverted = await client.patch(
        "/api/v1/period-lock",
        headers=headers,
        json={"lock_date": "2024-01-31", "hard_lock_date": "2024-06-30"},
    )
    assert inverted.status_code == 422, inverted.text

    applied = await _set_lock(client, headers, lock_date="2024-12-31")
    assert applied.status_code == 200, applied.text
    missing_reason = await _set_lock(client, headers, lock_date=None, include_lock=True)
    assert missing_reason.status_code == 422, missing_reason.text
    short_reason = await _set_lock(
        client, headers, lock_date=None, reason="too short", include_lock=True
    )
    assert short_reason.status_code == 422, short_reason.text
    unlocked = await _set_lock(
        client, headers, lock_date=None, reason=_UNLOCK_REASON, include_lock=True
    )
    assert unlocked.status_code == 200, unlocked.text
    assert unlocked.json()["data"]["lock_date"] is None
    assert unlocked.json()["data"]["lock_reason"] == _UNLOCK_REASON


@pytest.mark.asyncio
async def test_period_lock_writes_audit_row(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    applied = await _set_lock(client, headers, lock_date="2024-12-31")
    assert applied.status_code == 200, applied.text
    logs = await client.get("/api/v1/audit-logs?action=UPDATE&page_size=100", headers=headers)
    assert logs.status_code == 200, logs.text
    match = next(item for item in logs.json()["data"] if item["entity_type"] == "period_lock")
    detail = await client.get(f"/api/v1/audit-logs/{match['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    new_values = detail.json()["data"]["new_values"]
    assert new_values["lock_date"] == "2024-12-31"
    assert new_values["acknowledge_negative_stock"] is False


@pytest.mark.asyncio
async def test_idempotent_post_replay_after_lock(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=product_id, qty_delta="5"
    )
    doc = created["body"]["data"]
    key = uuid4().hex
    posted = await client.post(
        f"/api/v1/stock-adjustments/{doc['id']}/post",
        headers=_if_match(headers, doc["version"], key=key),
    )
    assert posted.status_code == 200, posted.text
    locked = await _set_lock(client, headers, lock_date="2024-12-31")
    assert locked.status_code == 200, locked.text
    replay = await client.post(
        f"/api/v1/stock-adjustments/{doc['id']}/post",
        headers=_if_match(headers, posted.json()["data"]["version"], key=key),
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["status"] == "POSTED"


@pytest.mark.asyncio
async def test_preview_lists_unposted_documents(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    dest_id = (
        await client.post(
            "/api/v1/warehouses",
            headers=headers,
            json={"code": f"WH-{uuid4().hex[:8]}", "name": "Overflow"},
        )
    ).json()["data"]["id"]
    adjustment = await client.post(
        "/api/v1/stock-adjustments",
        headers=headers,
        json={
            "warehouse_id": ids["main"],
            "reason": "OPENING_STOCK",
            "document_date": "2020-01-15",
            "lines": [{"product_id": product_id, "qty_delta": "5"}],
        },
    )
    transfer = await client.post(
        "/api/v1/stock-transfers",
        headers=headers,
        json={
            "from_warehouse_id": ids["main"],
            "to_warehouse_id": dest_id,
            "document_date": "2020-01-20",
            "lines": [{"product_id": product_id, "qty": "1"}],
        },
    )
    assert adjustment.status_code == 201, adjustment.text
    assert transfer.status_code == 201, transfer.text
    preview = await client.get("/api/v1/period-lock/preview?lock_date=2024-12-31", headers=headers)
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    types = {item["document_type"] for item in data["unposted_documents"]}
    assert types == {"stock_adjustment", "stock_transfer"}
    assert data["unposted_documents_total_count"] == 2
