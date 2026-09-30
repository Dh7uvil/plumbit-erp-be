"""Shared FastAPI helpers for import/export endpoints."""

from __future__ import annotations

import json

from fastapi import UploadFile

from app.common.imex.parser import suggest_mapping
from app.common.imex.schemas import ImexMappingEntry
from app.common.imex.service import catalog_for, parse_tabular
from app.common.utils.files import ensure_within_size_limit, max_upload_bytes
from app.core.config import get_settings
from app.core.exceptions import ValidationError

_READ_CHUNK_SIZE = 1024 * 1024


async def read_upload(file: UploadFile) -> tuple[str | None, bytes]:
    settings = get_settings()
    max_bytes = max_upload_bytes(settings.max_upload_size_mb)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValidationError(
                f"File exceeds the maximum size of {settings.max_upload_size_mb} MB",
                details={
                    "max_upload_size_mb": settings.max_upload_size_mb,
                    "size_bytes": total,
                },
            )
        chunks.append(chunk)
    content = b"".join(chunks)
    ensure_within_size_limit(
        len(content), max_upload_size_mb=settings.max_upload_size_mb
    )
    return file.filename, content


def parse_mapping_json(raw: str | None) -> list[ImexMappingEntry]:
    if raw is None or not raw.strip():
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("Column mapping must be valid JSON") from exc
    if not isinstance(payload, list):
        raise ValidationError("Column mapping must be a JSON array")
    return [ImexMappingEntry.model_validate(item) for item in payload]


def mapping_or_suggested(
    resource: str, *, filename: str | None, content: bytes, mapping: list[ImexMappingEntry]
) -> list[ImexMappingEntry]:
    if mapping:
        return mapping
    fields = catalog_for(resource)
    headers, _rows = parse_tabular(filename, content)
    suggested = suggest_mapping(headers, fields)
    if not suggested:
        raise ValidationError("Column mapping is required")
    return suggested
