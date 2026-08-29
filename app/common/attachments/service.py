"""Attachment use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import IDENTITY_MODULE
from app.common.attachments.models import Attachment
from app.common.attachments.repository import AttachmentRepository
from app.common.attachments.schemas import AttachmentDetailResponse, AttachmentResponse
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.files import ValidatedUpload, validate_upload
from app.core.config import Settings
from app.core.enums import AttachmentEntityType, AuditAction
from app.core.exceptions import ResourceNotFoundError
from app.db.session import transaction
from app.integrations.storage.client import S3Storage, build_object_key


class AttachmentService:
    def __init__(
        self,
        session: AsyncSession,
        storage: S3Storage,
        settings: Settings,
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
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
    ) -> tuple[list[AttachmentResponse], int]:
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters={"entity_type": entity_type.value, "entity_id": entity_id},
        )
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, attachment_id: UUID) -> AttachmentDetailResponse:
        row = await self._require(tenant_id, attachment_id)
        download_url = await self.storage.presigned_get_url(key=row.storage_key)
        return self._to_detail(row, download_url=download_url)

    async def create(
        self,
        tenant_id: UUID,
        *,
        entity_type: AttachmentEntityType,
        entity_id: UUID,
        filename: str | None,
        content: bytes,
        actor_user_id: UUID,
    ) -> AttachmentResponse:
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
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.storage.upload(
                key=storage_key,
                body=validated.content,
                content_type=validated.content_type,
            )
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=IDENTITY_MODULE,
                entity_type="attachment",
                entity_id=row.id,
                new_values={
                    "entity_type": entity_type.value,
                    "entity_id": entity_id,
                    "original_filename": validated.filename,
                    "content_type": validated.content_type,
                    "size_bytes": validated.size_bytes,
                },
            )
            return self._to_response(row)

    async def delete(
        self, tenant_id: UUID, attachment_id: UUID, *, actor_user_id: UUID
    ) -> AttachmentResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, attachment_id)
            response = self._to_response(row)
            await self.repo.soft_delete(tenant_id, attachment_id)
            await self.storage.delete(key=row.storage_key)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=IDENTITY_MODULE,
                entity_type="attachment",
                entity_id=attachment_id,
                old_values={
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "original_filename": row.original_filename,
                    "storage_key": row.storage_key,
                },
            )
            return response

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

    @staticmethod
    def _to_response(row: Attachment) -> AttachmentResponse:
        return AttachmentResponse.model_validate(row)

    @staticmethod
    def _to_detail(row: Attachment, *, download_url: str) -> AttachmentDetailResponse:
        return AttachmentDetailResponse(
            **AttachmentResponse.model_validate(row).model_dump(),
            download_url=download_url,
        )
