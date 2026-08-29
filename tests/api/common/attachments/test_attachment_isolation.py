"""API tests for attachments, including tenant isolation."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.integrations.storage.client import get_storage
from tests.conftest import login_headers, provision_admin

_JSON = b'{"ok": true}'


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
    entity_id: str | None = None,
    filename: str = "note.json",
    content: bytes = _JSON,
) -> Any:
    parent_id = entity_id or str(uuid4())
    return await client.post(
        "/api/v1/attachments",
        headers=headers,
        data={"entity_type": "CUSTOMER", "entity_id": parent_id},
        files={"file": (filename, content, "application/json")},
    )


@pytest.mark.asyncio
async def test_attachment_upload_list_get_and_delete(
    client: AsyncClient, fake_s3: FakeS3Client
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    entity_id = str(uuid4())
    created = await _upload(client, headers, entity_id=entity_id)
    assert created.status_code == 201, created.text
    payload = created.json()["data"]
    attachment_id = payload["id"]
    assert payload["entity_type"] == "CUSTOMER"
    assert payload["original_filename"] == "note.json"
    assert payload["content_type"] == "application/json"
    assert fake_s3.objects

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
    assert fake_s3.objects == {}
    missing = await client.get(f"/api/v1/attachments/{attachment_id}", headers=headers)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_attachment_tenant_isolation(client: AsyncClient, fake_s3: FakeS3Client) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    entity_id = str(uuid4())
    created = await _upload(client, headers_a, entity_id=entity_id)
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
    assert listed.status_code == 200
    assert all(item["id"] != attachment_id for item in listed.json()["data"])

    deleted = await client.delete(f"/api/v1/attachments/{attachment_id}", headers=headers_b)
    assert deleted.status_code == 404
