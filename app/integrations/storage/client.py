"""Boto3 S3 client used for both MinIO and AWS S3."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any, Protocol, cast
from uuid import UUID

from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from app.core.config import Settings, get_settings
from app.core.exceptions import IntegrationError

LOGO_PRESIGN_TTL_SECONDS = 3600


class S3ClientProtocol(Protocol):
    """Subset of the boto3 S3 client used by this adapter."""

    def put_object(self, **kwargs: Any) -> Any: ...

    def delete_object(self, **kwargs: Any) -> Any: ...

    def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str: ...


def build_object_key(
    *,
    tenant_id: UUID,
    entity_type: str,
    entity_id: UUID,
    attachment_id: UUID,
    filename: str,
) -> str:
    """Build a tenant-prefixed object key. ``filename`` must already be sanitized."""

    return f"{tenant_id}/{entity_type}/{entity_id}/{attachment_id}/{filename}"


def build_org_logo_key(*, tenant_id: UUID, filename: str) -> str:
    """Build the object key for a tenant's single organization logo."""

    return f"{tenant_id}/organization/logo/{filename}"


class S3Storage:
    """Upload, delete, and presign objects on an S3-compatible bucket."""

    def __init__(
        self,
        client: S3ClientProtocol,
        *,
        bucket: str,
        presign_ttl_seconds: int,
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._presign_ttl_seconds = presign_ttl_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> S3Storage:
        """Build a client from application settings.

        ``S3_ENDPOINT_URL`` selects MinIO (path-style). Leaving it unset talks to AWS S3.
        """

        if not settings.s3_bucket_name:
            raise IntegrationError("Object storage is not configured")
        return cls(
            _build_boto3_client(settings),
            bucket=settings.s3_bucket_name,
            presign_ttl_seconds=settings.s3_presign_ttl_seconds,
        )

    async def upload(self, *, key: str, body: bytes, content_type: str) -> None:
        """Put an object. Runs boto3 off the event loop."""

        await asyncio.to_thread(self._upload_sync, key, body, content_type)

    async def delete(self, *, key: str) -> None:
        """Delete an object. Runs boto3 off the event loop."""

        await asyncio.to_thread(self._delete_sync, key)

    async def presigned_get_url(self, *, key: str, expires_in: int | None = None) -> str:
        """Return a short-lived GET URL for a private object."""

        ttl = self._presign_ttl_seconds if expires_in is None else expires_in
        return await asyncio.to_thread(self._presign_sync, key, ttl)

    def _upload_sync(self, key: str, body: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise IntegrationError("Failed to store uploaded file") from exc

    def _delete_sync(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise IntegrationError("Failed to delete stored file") from exc

    def _presign_sync(self, key: str, expires_in: int) -> str:
        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except (BotoCoreError, ClientError) as exc:
            raise IntegrationError("Failed to create download URL") from exc


def _build_boto3_client(settings: Settings) -> S3ClientProtocol:
    import boto3  # type: ignore[import-untyped]

    kwargs: dict[str, Any] = {"service_name": "s3"}
    if settings.aws_region:
        kwargs["region_name"] = settings.aws_region
    if settings.aws_access_key_id is not None and settings.aws_secret_access_key is not None:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id.get_secret_value()
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key.get_secret_value()
    if settings.s3_endpoint_url is not None:
        kwargs["endpoint_url"] = str(settings.s3_endpoint_url).rstrip("/")
        kwargs["config"] = Config(s3={"addressing_style": "path"})
    return cast(S3ClientProtocol, boto3.client(**kwargs))


@lru_cache
def get_storage() -> S3Storage:
    """Return the process-wide storage adapter."""

    return S3Storage.from_settings(get_settings())


def get_optional_storage() -> S3Storage | None:
    """Return storage when a bucket is configured; otherwise None."""

    if not get_settings().s3_bucket_name:
        return None
    return get_storage()


async def presign_logo_url(storage: S3Storage | None, key: str | None) -> str | None:
    """Presign a logo GET URL, or return None when there is no logo or storage."""

    if not key or storage is None:
        return None
    return await storage.presigned_get_url(key=key, expires_in=LOGO_PRESIGN_TTL_SECONDS)
