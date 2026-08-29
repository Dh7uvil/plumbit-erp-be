"""Unit tests for the S3-compatible storage adapter."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError

from app.core.exceptions import IntegrationError
from app.integrations.storage.client import S3Storage, build_object_key, build_org_logo_key


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}

    def put_object(self, **kwargs: Any) -> None:
        key = kwargs["Key"]
        self.objects[key] = kwargs["Body"]
        self.content_types[key] = kwargs["ContentType"]

    def delete_object(self, **kwargs: Any) -> None:
        self.objects.pop(kwargs["Key"], None)
        self.content_types.pop(kwargs["Key"], None)

    def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str:
        params = kwargs.get("Params") or {}
        key = params.get("Key", "")
        expires = kwargs.get("ExpiresIn", 0)
        return f"https://example.test/{key}?expires={expires}"


class BoomS3Client(FakeS3Client):
    def put_object(self, **kwargs: Any) -> None:
        raise ClientError({"Error": {"Code": "500", "Message": "fail"}}, "PutObject")


def test_build_object_key_shape() -> None:
    tenant_id = UUID("11111111-1111-1111-1111-111111111111")
    entity_id = UUID("22222222-2222-2222-2222-222222222222")
    attachment_id = UUID("33333333-3333-3333-3333-333333333333")
    assert (
        build_object_key(
            tenant_id=tenant_id,
            entity_type="CUSTOMER",
            entity_id=entity_id,
            attachment_id=attachment_id,
            filename="quote.pdf",
        )
        == "11111111-1111-1111-1111-111111111111/CUSTOMER/"
        "22222222-2222-2222-2222-222222222222/"
        "33333333-3333-3333-3333-333333333333/quote.pdf"
    )


def test_build_org_logo_key_shape() -> None:
    tenant_id = UUID("11111111-1111-1111-1111-111111111111")
    assert (
        build_org_logo_key(tenant_id=tenant_id, filename="acme.png")
        == "11111111-1111-1111-1111-111111111111/organization/logo/acme.png"
    )


@pytest.mark.asyncio
async def test_storage_upload_delete_and_presign_with_fake_client() -> None:
    client = FakeS3Client()
    storage = S3Storage(client, bucket="test-bucket", presign_ttl_seconds=90)
    key = f"{uuid4()}/CUSTOMER/{uuid4()}/{uuid4()}/file.pdf"
    await storage.upload(key=key, body=b"%PDF-1.4\n", content_type="application/pdf")
    assert client.objects[key] == b"%PDF-1.4\n"
    assert client.content_types[key] == "application/pdf"
    url = await storage.presigned_get_url(key=key)
    assert key in url
    assert "expires=90" in url
    long_lived = await storage.presigned_get_url(key=key, expires_in=3600)
    assert "expires=3600" in long_lived
    await storage.delete(key=key)
    assert key not in client.objects


@pytest.mark.asyncio
async def test_storage_maps_client_errors() -> None:
    storage = S3Storage(BoomS3Client(), bucket="test-bucket", presign_ttl_seconds=60)
    with pytest.raises(IntegrationError, match="store uploaded file"):
        await storage.upload(key="a/b", body=b"x", content_type="application/pdf")
