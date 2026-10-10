"""Entry book master routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.catalog import VOUCHER_READ, VOUCHER_UPDATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.erp.accounting.entry_books.dependencies import EntryBookServiceDependency
from app.erp.accounting.entry_books.schemas import (
    EntryBookFilter,
    EntryBookResponse,
    EntryBookUpdate,
)

router = APIRouter(prefix="/entry-books", tags=["Entry Books"])


@router.get("", response_model=ApiResponse[list[EntryBookResponse]])
async def list_entry_books(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: EntryBookServiceDependency,
    filters: Annotated[EntryBookFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(VOUCHER_READ))],
) -> ApiResponse[list[EntryBookResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        voucher_type=filters.voucher_type,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@router.get("/{entry_book_id}", response_model=ApiResponse[EntryBookResponse])
async def get_entry_book(
    entry_book_id: UUID,
    tenant: TenantContextDependency,
    service: EntryBookServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(VOUCHER_READ))],
) -> ApiResponse[EntryBookResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, entry_book_id))


@router.patch("/{entry_book_id}", response_model=ApiResponse[EntryBookResponse])
async def update_entry_book(
    entry_book_id: UUID,
    payload: EntryBookUpdate,
    tenant: TenantContextDependency,
    service: EntryBookServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(VOUCHER_UPDATE))],
) -> ApiResponse[EntryBookResponse]:
    row = await service.update(
        tenant.tenant_id,
        entry_book_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=row, message="Entry book updated")
