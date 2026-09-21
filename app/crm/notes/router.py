"""Note routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import NOTE_CREATE, NOTE_DELETE, NOTE_READ, NOTE_UPDATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.crm.notes.dependencies import NoteServiceDependency
from app.crm.notes.schemas import NoteCreate, NoteFilter, NoteResponse, NoteUpdate

router = APIRouter(prefix="/notes", tags=["Notes"])


@router.get("", response_model=ApiResponse[list[NoteResponse]])
async def list_notes(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: NoteServiceDependency,
    filters: Annotated[NoteFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(NOTE_READ))],
) -> ApiResponse[list[NoteResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        related_entity_type=filters.related_entity_type.value
        if filters.related_entity_type
        else None,
        related_entity_id=filters.related_entity_id,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[NoteResponse], status_code=status.HTTP_201_CREATED)
async def create_note(
    payload: NoteCreate,
    tenant: TenantContextDependency,
    service: NoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(NOTE_CREATE))],
) -> ApiResponse[NoteResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Note created successfully")


@router.get("/{note_id}", response_model=ApiResponse[NoteResponse])
async def get_note(
    note_id: UUID,
    tenant: TenantContextDependency,
    service: NoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(NOTE_READ))],
) -> ApiResponse[NoteResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, note_id))


@router.patch("/{note_id}", response_model=ApiResponse[NoteResponse])
async def update_note(
    note_id: UUID,
    payload: NoteUpdate,
    tenant: TenantContextDependency,
    service: NoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(NOTE_UPDATE))],
) -> ApiResponse[NoteResponse]:
    row = await service.update(tenant.tenant_id, note_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Note updated successfully")


@router.delete("/{note_id}", response_model=ApiResponse[NoteResponse])
async def delete_note(
    note_id: UUID,
    tenant: TenantContextDependency,
    service: NoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(NOTE_DELETE))],
) -> ApiResponse[NoteResponse]:
    row = await service.delete(tenant.tenant_id, note_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Note deleted successfully")
