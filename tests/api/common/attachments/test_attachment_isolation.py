"""API tests for attachments, including tenant isolation and access control."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.integrations.storage.client import get_storage
from tests.api.erp.quotation.test_routes import _create_customer
from tests.api.inventory_management.stock.test_stock_routes import (
    _create_adjustment,
    _create_product,
    _post_document,
    _seeded,
    _user_headers,
)
from tests.conftest import login_headers, provision_admin

_JSON = b'{"ok": true}'
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs: Any) -> None:
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def delete_object(self, **kwargs: Any) -> None:
        self.objects.pop(kwargs["Key"], None)

    def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str:
        params = kwargs.get("Params") or {}
        key = params.get("Key", "")
        return f"https://example.test/{key}?expires={kwargs.get('ExpiresIn', 0)}"


@pytest.fixture
def fake_s3(app):
    from app.integrations.storage.client import S3Storage

    client = FakeS3Client()
    storage = S3Storage(client, bucket="test-bucket", presign_ttl_seconds=60)
    app.dependency_overrides[get_storage] = lambda: storage
    yield client
    app.dependency_overrides.pop(get_storage, None)


async def _upload(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    entity_type: str,
    entity_id: str,
    filename: str = "note.json",
    content: bytes = _JSON,
    content_type: str = "application/json",
    category: str | None = None,
) -> Any:
    data: dict[str, str] = {"entity_type": entity_type, "entity_id": entity_id}
    if category is not None:
        data["category"] = category
    return await client.post(
        "/api/v1/attachments",
        headers=headers,
        data=data,
        files={"file": (filename, content, content_type)},
    )


@pytest.mark.asyncio
async def test_attachment_upload_list_get_and_delete(
    client: AsyncClient, fake_s3: FakeS3Client
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    entity_id = await _create_customer(client, headers)
    created = await _upload(client, headers, entity_type="CUSTOMER", entity_id=entity_id)
    assert created.status_code == 201, created.text
    payload = created.json()["data"]
    attachment_id = payload["id"]
    assert payload["entity_type"] == "CUSTOMER"
    assert payload["original_filename"] == "note.json"
    assert payload["content_type"] == "application/json"
    assert payload["thumbnail_url"] is None
    assert fake_s3.objects
    stored_keys = set(fake_s3.objects)

    listed = await client.get(
        "/api/v1/attachments",
        headers=headers,
        params={"entity_type": "CUSTOMER", "entity_id": entity_id},
    )
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == attachment_id for item in listed.json()["data"])

    fetched = await client.get(f"/api/v1/attachments/{attachment_id}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["data"]["download_url"].startswith("https://example.test/")

    deleted = await client.delete(f"/api/v1/attachments/{attachment_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert set(fake_s3.objects) == stored_keys
    missing = await client.get(f"/api/v1/attachments/{attachment_id}", headers=headers)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_attachment_missing_parent_is_not_found(
    client: AsyncClient, fake_s3: FakeS3Client
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    created = await _upload(client, headers, entity_type="CUSTOMER", entity_id=str(uuid4()))
    assert created.status_code == 404, created.text
    assert created.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_attachment_list_requires_owning_read(
    client: AsyncClient, fake_s3: FakeS3Client
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    entity_id = await _create_customer(client, headers)
    created = await _upload(client, headers, entity_type="CUSTOMER", entity_id=entity_id)
    assert created.status_code == 201, created.text

    attachment_only = await _user_headers(
        client,
        headers,
        tenant_id,
        codes=("identity.attachment.read", "identity.attachment.create"),
    )
    listed = await client.get(
        "/api/v1/attachments",
        headers=attachment_only,
        params={"entity_type": "CUSTOMER", "entity_id": entity_id},
    )
    assert listed.status_code == 403, listed.text
    assert listed.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_attachment_delete_blocked_on_posted_parent(
    client: AsyncClient, fake_s3: FakeS3Client
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    ids = await _seeded(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await _create_adjustment(
        client, headers, warehouse_id=ids["main"], product_id=product_id
    )
    assert created["status_code"] == 201, created["text"]
    doc = created["body"]["data"]
    posted = await _post_document(
        client, headers, f"/api/v1/stock-adjustments/{doc['id']}/post", doc["version"]
    )
    assert posted.status_code == 200, posted.text

    uploaded = await _upload(client, headers, entity_type="STOCK_ADJUSTMENT", entity_id=doc["id"])
    assert uploaded.status_code == 201, uploaded.text
    attachment_id = uploaded.json()["data"]["id"]
    stored_keys = set(fake_s3.objects)
    deleted = await client.delete(f"/api/v1/attachments/{attachment_id}", headers=headers)
    assert deleted.status_code == 409, deleted.text
    assert deleted.json()["error"]["code"] == "FINANCIAL_TRANSACTION_LOCKED"
    assert set(fake_s3.objects) == stored_keys


@pytest.mark.asyncio
async def test_attachment_category_filter_and_thumbnail(
    client: AsyncClient, fake_s3: FakeS3Client
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    entity_id = await _create_customer(client, headers)
    created = await _upload(
        client,
        headers,
        entity_type="CUSTOMER",
        entity_id=entity_id,
        filename="photo.png",
        content=_PNG,
        content_type="image/png",
        category="QC_PHOTO",
    )
    assert created.status_code == 201, created.text
    payload = created.json()["data"]
    assert payload["category"] == "QC_PHOTO"
    assert payload["thumbnail_url"] is not None
    assert payload["image_width"] == 1
    assert payload["image_height"] == 1

    listed = await client.get(
        "/api/v1/attachments",
        headers=headers,
        params={"entity_type": "CUSTOMER", "entity_id": entity_id, "category": "QC_PHOTO"},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"][0]["thumbnail_url"] is not None

    patched = await client.patch(
        f"/api/v1/attachments/{payload['id']}",
        headers=headers,
        json={"category": "TRADE_LICENCE"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["category"] == "TRADE_LICENCE"


@pytest.mark.asyncio
async def test_attachment_unregistered_entity_type(
    client: AsyncClient, fake_s3: FakeS3Client
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    created = await _upload(client, headers, entity_type="CUSTOMER_PAYMENT", entity_id=str(uuid4()))
    assert created.status_code == 422, created.text
    assert created.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_attachment_tenant_isolation(client: AsyncClient, fake_s3: FakeS3Client) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    entity_id = await _create_customer(client, headers_a)
    created = await _upload(client, headers_a, entity_type="CUSTOMER", entity_id=entity_id)
    assert created.status_code == 201, created.text
    attachment_id = created.json()["data"]["id"]

    fetched = await client.get(f"/api/v1/attachments/{attachment_id}", headers=headers_b)
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    listed = await client.get(
        "/api/v1/attachments",
        headers=headers_b,
        params={"entity_type": "CUSTOMER", "entity_id": entity_id},
    )
    assert listed.status_code == 404
    assert listed.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    deleted = await client.delete(f"/api/v1/attachments/{attachment_id}", headers=headers_b)
    assert deleted.status_code == 404
