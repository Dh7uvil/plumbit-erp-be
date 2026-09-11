"""Shared FastAPI helpers for import/export endpoints."""

from __future__ import annotations

import json

from fastapi import UploadFile

from app.common.imex.parser import suggest_mapping
from app.common.imex.schemas import ImexMappingEntry
from app.common.imex.service import catalog_for, parse_tabular
from app.core.exceptions import ValidationError


async def read_upload(file: UploadFile) -> tuple[str | None, bytes]:
    content = await file.read()
    if not content:
        raise ValidationError("File is empty")
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
