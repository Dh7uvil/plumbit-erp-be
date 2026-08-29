"""Attachment routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.auth.catalog import ATTACHMENT_CREATE, ATTACHMENT_DELETE, ATTACHMENT_READ
from app.common.attachments.dependencies import AttachmentServiceDependency
from app.common.attachments.schemas import (
    AttachmentDetailResponse,
    AttachmentFilter,
    AttachmentResponse,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.files import max_upload_bytes
from app.core.config import get_settings
from app.core.enums import AttachmentEntityType
from app.core.exceptions import ValidationError

router = APIRouter(prefix="/attachments", tags=["Attachments"])

_READ_CHUNK_SIZE = 64 * 1024


@router.get("", response_model=ApiResponse[list[AttachmentResponse]])
async def list_attachments(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: AttachmentServiceDependency,
    filters: Annotated[AttachmentFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(ATTACHMENT_READ))],
) -> ApiResponse[list[AttachmentResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        entity_type=filters.entity_type,
        entity_id=filters.entity_id,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[AttachmentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_attachment(
    tenant: TenantContextDependency,
    service: AttachmentServiceDependency,
    entity_type: Annotated[AttachmentEntityType, Form()],
    entity_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    _: Annotated[CurrentUser, Depends(require_permission(ATTACHMENT_CREATE))],
) -> ApiResponse[AttachmentResponse]:
    content = await _read_upload(
        file, max_bytes=max_upload_bytes(get_settings().max_upload_size_mb)
    )
    row = await service.create(
        tenant.tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        filename=file.filename,
        content=content,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=row, message="Attachment created successfully")


@router.get("/{attachment_id}", response_model=ApiResponse[AttachmentDetailResponse])
async def get_attachment(
    attachment_id: UUID,
    tenant: TenantContextDependency,
    service: AttachmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ATTACHMENT_READ))],
) -> ApiResponse[AttachmentDetailResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, attachment_id))


@router.delete("/{attachment_id}", response_model=ApiResponse[AttachmentResponse])
async def delete_attachment(
    attachment_id: UUID,
    tenant: TenantContextDependency,
    service: AttachmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ATTACHMENT_DELETE))],
) -> ApiResponse[AttachmentResponse]:
    row = await service.delete(tenant.tenant_id, attachment_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Attachment deleted successfully")


async def _read_upload(file: UploadFile, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValidationError(
                "File exceeds the maximum upload size",
                details={"max_bytes": max_bytes},
            )
        chunks.append(chunk)
    return b"".join(chunks)
