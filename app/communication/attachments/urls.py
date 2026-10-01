"""Same-origin attachment URLs for clients that cannot reach local MinIO (e.g. ngrok)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from app.core.config import Settings

CHAT_ATTACHMENT_CONTENT_PREFIX = "/api/v1/communication/attachments"


def use_proxied_attachment_urls(settings: Settings) -> bool:
    """Presigned MinIO URLs use the internal endpoint and fail off localhost."""
    return settings.s3_endpoint_url is not None


def chat_attachment_content_url(
    attachment_id: UUID,
    *,
    variant: Literal["thumbnail", "original"] = "original",
) -> str:
    if variant == "thumbnail":
        return (
            f"{CHAT_ATTACHMENT_CONTENT_PREFIX}/{attachment_id}/content?variant=thumbnail"
        )
    return f"{CHAT_ATTACHMENT_CONTENT_PREFIX}/{attachment_id}/content"
