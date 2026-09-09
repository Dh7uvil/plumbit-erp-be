"""Attachment use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import IDENTITY_MODULE
from app.common.attachments.entities import EntityRef, require_spec
from app.common.attachments.models import Attachment
from app.common.attachments.repository import AttachmentRepository
from app.common.attachments.schemas import (
    AttachmentDetailResponse,
    AttachmentResponse,
    AttachmentUpdate,
)
from app.common.attachments.thumbnails import generate_thumbnail, is_thumbnail_source
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.files import ValidatedUpload, validate_upload
from app.core.config import Settings
from app.core.enums import AttachmentCategory, AttachmentEntityType, AuditAction
from app.core.exceptions import (
    FinancialTransactionLockedError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from app.core.permissions import has_permission
from app.db.session import transaction
from app.integrations.storage.client import S3Storage, build_object_key


def build_thumbnail_key(
    *,
    tenant_id: UUID,
    entity_type: str,
    entity_id: UUID,
    attachment_id: UUID,
) -> str:
    return f"{tenant_id}/{entity_type}/{entity_id}/{attachment_id}/thumb/{attachment_id}.jpg"


def _attachment_snapshot(row: Attachment) -> dict[str, object]:
    return {
        "entity_type": row.entity_type,
        "original_filename": row.original_filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "category": row.category,
    }


class AttachmentService:
    def __init__(
        self,
        session: AsyncSession,
        storage: S3Storage,
        settings: Settings,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
        self.actor_permissions = actor_permissions
        self.repo = AttachmentRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        entity_type: AttachmentEntityType,
        entity_id: UUID,
        category: AttachmentCategory | None = None,
    ) -> tuple[list[AttachmentResponse], int]:
        await self._resolve(tenant_id, entity_type, entity_id, write=False)
        filters: dict[str, object] = {
            "entity_type": entity_type.value,
            "entity_id": entity_id,
        }
        if category is not None:
            filters["category"] = category.value
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
        )
        return [await self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, attachment_id: UUID) -> AttachmentDetailResponse:
        row = await self._require(tenant_id, attachment_id)
        await self._resolve(
            tenant_id,
            AttachmentEntityType(row.entity_type),
            row.entity_id,
            write=False,
        )
        download_url = await self.storage.presigned_get_url(key=row.storage_key)
        return await self._to_detail(row, download_url=download_url)

    async def create(
        self,
        tenant_id: UUID,
        *,
        entity_type: AttachmentEntityType,
        entity_id: UUID,
        filename: str | None,
        content: bytes,
        actor_user_id: UUID,
        category: AttachmentCategory | None = None,
    ) -> AttachmentResponse:
        await self._resolve(tenant_id, entity_type, entity_id, write=True)
        validated = self._validate(content, filename=filename)
        async with transaction(self.session):
            row = await self.repo.create(
                tenant_id,
                {
                    "entity_type": entity_type.value,
                    "entity_id": entity_id,
                    "original_filename": validated.filename,
                    "content_type": validated.content_type,
                    "size_bytes": validated.size_bytes,
                    "storage_key": "pending",
                    "category": category.value if category is not None else None,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            storage_key = build_object_key(
                tenant_id=tenant_id,
                entity_type=entity_type.value,
                entity_id=entity_id,
                attachment_id=row.id,
                filename=validated.filename,
            )
            row.storage_key = storage_key
            thumbnail_bytes = self._apply_thumbnail(row, validated)
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.storage.upload(
                key=storage_key,
                body=validated.content,
                content_type=validated.content_type,
            )
            if row.thumbnail_storage_key and thumbnail_bytes:
                await self.storage.upload(
                    key=row.thumbnail_storage_key,
                    body=thumbnail_bytes,
                    content_type="image/jpeg",
                )
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=IDENTITY_MODULE,
                entity_type="attachment",
                entity_id=row.id,
                new_values=_attachment_snapshot(row),
            )
            return await self._to_response(row)

    async def update(
        self,
        tenant_id: UUID,
        attachment_id: UUID,
        payload: AttachmentUpdate,
        *,
        actor_user_id: UUID,
    ) -> AttachmentResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, attachment_id)
            await self._resolve(
                tenant_id,
                AttachmentEntityType(row.entity_type),
                row.entity_id,
                write=True,
            )
            old_values = _attachment_snapshot(row)
            row.category = payload.category.value if payload.category is not None else None
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="attachment",
                entity_id=row.id,
                old_values=old_values,
                new_values=_attachment_snapshot(row),
            )
            return await self._to_response(row)

    async def delete(
        self, tenant_id: UUID, attachment_id: UUID, *, actor_user_id: UUID
    ) -> AttachmentResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, attachment_id)
            parent = await self._resolve(
                tenant_id,
                AttachmentEntityType(row.entity_type),
                row.entity_id,
                write=True,
            )
            if parent.is_posted:
                raise FinancialTransactionLockedError("Posted document evidence cannot be deleted")
            response = await self._to_response(row)
            await self.repo.soft_delete(tenant_id, attachment_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=IDENTITY_MODULE,
                entity_type="attachment",
                entity_id=attachment_id,
                old_values=_attachment_snapshot(row),
            )
            return response

    async def _resolve(
        self,
        tenant_id: UUID,
        entity_type: AttachmentEntityType,
        entity_id: UUID,
        *,
        write: bool,
    ) -> EntityRef:
        spec = require_spec(entity_type)
        required = spec.write_permission if write else spec.read_permission
        if not has_permission(self.actor_permissions, required):
            raise PermissionDeniedError()
        ref = await spec.probe(self.session, tenant_id, entity_id)
        if not ref.exists:
            raise ResourceNotFoundError("Parent record not found")
        return ref

    async def _require(self, tenant_id: UUID, attachment_id: UUID) -> Attachment:
        row = await self.repo.get(tenant_id, attachment_id)
        if row is None:
            raise ResourceNotFoundError("Attachment not found")
        return row

    def _validate(self, content: bytes, *, filename: str | None) -> ValidatedUpload:
        return validate_upload(
            content,
            filename=filename,
            max_upload_size_mb=self.settings.max_upload_size_mb,
            allowed_mime_types=self.settings.allowed_upload_mime_types,
        )

    def _apply_thumbnail(self, row: Attachment, validated: ValidatedUpload) -> bytes | None:
        if not is_thumbnail_source(validated.content_type):
            return None
        generated = generate_thumbnail(validated.content)
        if generated is None:
            return None
        thumb_bytes, width, height = generated
        row.image_width = width
        row.image_height = height
        row.thumbnail_storage_key = build_thumbnail_key(
            tenant_id=row.tenant_id,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            attachment_id=row.id,
        )
        return thumb_bytes

    async def _to_response(self, row: Attachment) -> AttachmentResponse:
        thumbnail_url: str | None = None
        if row.thumbnail_storage_key:
            thumbnail_url = await self.storage.presigned_get_url(key=row.thumbnail_storage_key)
        payload = AttachmentResponse.model_validate(row)
        return payload.model_copy(update={"thumbnail_url": thumbnail_url})

    async def _to_detail(self, row: Attachment, *, download_url: str) -> AttachmentDetailResponse:
        base = await self._to_response(row)
        return AttachmentDetailResponse(
            **base.model_dump(),
            download_url=download_url,
        )
