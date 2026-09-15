"""API tests for organization logo upload, replace, and delete."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.integrations.storage.client import get_optional_storage, get_storage
from tests.conftest import login_headers, provision_admin

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_JSON = b'{"ok": true}'


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs: Any) -> None:
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def delete_object(self, **kwargs: Any) -> None:
        self.objects.pop(kwargs["Key"], None)

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        return {"Body": _Body(self.objects[kwargs["Key"]]), "ContentType": "image/png"}

    def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str:
        params = kwargs.get("Params") or {}
        key = params.get("Key", "")
        return f"https://example.test/{key}?expires={kwargs.get('ExpiresIn', 0)}"


class _Body:
    def __init__(self, value: bytes) -> None:
        self.value = value

    def read(self) -> bytes:
        return self.value


@pytest.fixture
def fake_s3(app):
    from app.integrations.storage.client import S3Storage

    client = FakeS3Client()
    storage = S3Storage(client, bucket="test-bucket", presign_ttl_seconds=60)
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_optional_storage] = lambda: storage
    yield client
    app.dependency_overrides.pop(get_storage, None)
    app.dependency_overrides.pop(get_optional_storage, None)


@pytest.mark.asyncio
async def test_org_logo_upload_replace_delete_and_public_url(
    client: AsyncClient, fake_s3: FakeS3Client
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)

    uploaded = await client.post(
        "/api/v1/tenants/current/logo",
        headers=headers,
        files={"file": ("acme.png", _PNG, "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    data = uploaded.json()["data"]
    first_key = f"{tenant_id}/organization/logo/acme.png"
    assert first_key in fake_s3.objects
    assert data["logo_url"] == "/api/v1/tenants/current/logo"
    assert "expires=" not in data["logo_url"]
    assert "AWSAccessKeyId" not in data["logo_url"]
    assert "?" not in data["logo_url"]

    current = await client.get("/api/v1/tenants/current", headers=headers)
    assert current.status_code == 200, current.text
    assert current.json()["data"]["logo_url"] == "/api/v1/tenants/current/logo"

    current_logo = await client.get("/api/v1/tenants/current/logo", headers=headers)
    assert current_logo.status_code == 200
    assert current_logo.content == _PNG

    public = await client.get("/api/v1/tenants")
    assert public.status_code == 200, public.text
    match = next(item for item in public.json()["data"] if item["tenant_id"] == tenant_id)
    assert match["logo_url"] == f"/api/v1/tenants/{tenant_id}/logo"
    assert first_key not in match["logo_url"]

    public_logo = await client.get(match["logo_url"])
    assert public_logo.status_code == 200
    assert public_logo.content == _PNG

    replaced = await client.post(
        "/api/v1/tenants/current/logo",
        headers=headers,
        files={"file": ("new-logo.png", _PNG, "image/png")},
    )
    assert replaced.status_code == 200, replaced.text
    second_key = f"{tenant_id}/organization/logo/new-logo.png"
    assert first_key not in fake_s3.objects
    assert second_key in fake_s3.objects
    assert replaced.json()["data"]["logo_url"] == "/api/v1/tenants/current/logo"

    deleted = await client.delete("/api/v1/tenants/current/logo", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"]["logo_url"] is None
    assert fake_s3.objects == {}

    after = await client.get("/api/v1/tenants/current", headers=headers)
    assert after.status_code == 200
    assert after.json()["data"]["logo_url"] is None


@pytest.mark.asyncio
async def test_org_logo_rejects_non_image(client: AsyncClient, fake_s3: FakeS3Client) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    rejected = await client.post(
        "/api/v1/tenants/current/logo",
        headers=headers,
        files={"file": ("notes.json", _JSON, "application/json")},
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"
    assert fake_s3.objects == {}
