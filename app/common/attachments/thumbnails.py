"""Bounded JPEG thumbnails for image attachments.

Pillow is the only new Stage A dependency: FastAPI and SQLAlchemy cannot resize
images, and the gallery needs a max-512px preview without a second object fetch.
"""

from __future__ import annotations

import io
import logging

from app.common.utils.files import MIME_GIF, MIME_JPEG, MIME_PNG, MIME_WEBP

logger = logging.getLogger(__name__)

THUMBNAIL_MAX_PX = 512
THUMBNAIL_JPEG_QUALITY = 80
_IMAGE_MIME_TYPES = frozenset({MIME_JPEG, MIME_PNG, MIME_GIF, MIME_WEBP})


def is_thumbnail_source(content_type: str) -> bool:
    return content_type in _IMAGE_MIME_TYPES


def generate_thumbnail(
    content: bytes,
    *,
    max_px: int = THUMBNAIL_MAX_PX,
    quality: int = THUMBNAIL_JPEG_QUALITY,
) -> tuple[bytes, int, int] | None:
    """Return JPEG bytes plus original width/height, or None if the image cannot be read."""

    try:
        from PIL import Image
    except ImportError:
        logger.exception("pillow_missing")
        return None

    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            rgb = image.convert("RGB")
            rgb.thumbnail((max_px, max_px))
            buffer = io.BytesIO()
            rgb.save(buffer, format="JPEG", quality=quality, optimize=True)
            return buffer.getvalue(), width, height
    except Exception:
        logger.exception("thumbnail_generation_failed")
        return None
