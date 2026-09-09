"""Unit tests for bounded image thumbnails."""

from app.common.attachments.thumbnails import generate_thumbnail, is_thumbnail_source
from app.common.utils.files import MIME_JPEG, MIME_JSON, MIME_PNG

# 1x1 PNG
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_json_is_not_a_thumbnail_source() -> None:
    assert is_thumbnail_source(MIME_JSON) is False
    assert is_thumbnail_source(MIME_PNG) is True
    assert is_thumbnail_source(MIME_JPEG) is True


def test_generate_thumbnail_returns_jpeg_and_original_dimensions() -> None:
    result = generate_thumbnail(_PNG)
    assert result is not None
    body, width, height = result
    assert width == 1
    assert height == 1
    assert body.startswith(b"\xff\xd8\xff")
