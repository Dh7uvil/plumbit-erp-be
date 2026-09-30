"""Unit tests for imex upload helpers."""

import pytest
from fastapi import UploadFile
from io import BytesIO

from app.common.imex.http import read_upload
from app.core.config import get_settings
from app.core.exceptions import ValidationError


@pytest.mark.asyncio
async def test_read_upload_rejects_oversized_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_upload_size_mb", 1)
    oversized = b"x" * (1024 * 1024 + 1)
    upload = UploadFile(filename="big.csv", file=BytesIO(oversized))
    with pytest.raises(ValidationError, match="maximum size"):
        await read_upload(upload)


@pytest.mark.asyncio
async def test_read_upload_rejects_empty_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_upload_size_mb", 25)
    upload = UploadFile(filename="empty.csv", file=BytesIO(b""))
    with pytest.raises(ValidationError, match="empty"):
        await read_upload(upload)


@pytest.mark.asyncio
async def test_read_upload_accepts_within_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_upload_size_mb", 1)
    content = b"a,b\n1,2\n"
    upload = UploadFile(filename="rows.csv", file=BytesIO(content))
    filename, data = await read_upload(upload)
    assert filename == "rows.csv"
    assert data == content
