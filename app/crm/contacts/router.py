"""Contact routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import CONTACT_CREATE, CONTACT_DELETE, CONTACT_READ, CONTACT_UPDATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.crm.contacts.dependencies import ContactServiceDependency
from app.crm.contacts.schemas import ContactCreate, ContactFilter, ContactResponse, ContactUpdate

router = APIRouter(prefix="/contacts", tags=["Contacts"])


@router.get("", response_model=ApiResponse[list[ContactResponse]])
async def list_contacts(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: ContactServiceDependency,
    filters: Annotated[ContactFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CONTACT_READ))],
) -> ApiResponse[list[ContactResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        customer_id=filters.customer_id,
        is_primary=filters.is_primary,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[ContactResponse], status_code=status.HTTP_201_CREATED)
async def create_contact(
    payload: ContactCreate,
    tenant: TenantContextDependency,
    service: ContactServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONTACT_CREATE))],
) -> ApiResponse[ContactResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Contact created successfully")


@router.get("/{contact_id}", response_model=ApiResponse[ContactResponse])
async def get_contact(
    contact_id: UUID,
    tenant: TenantContextDependency,
    service: ContactServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONTACT_READ))],
) -> ApiResponse[ContactResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, contact_id))


@router.patch("/{contact_id}", response_model=ApiResponse[ContactResponse])
async def update_contact(
    contact_id: UUID,
    payload: ContactUpdate,
    tenant: TenantContextDependency,
    service: ContactServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONTACT_UPDATE))],
) -> ApiResponse[ContactResponse]:
    row = await service.update(tenant.tenant_id, contact_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Contact updated successfully")


@router.delete("/{contact_id}", response_model=ApiResponse[ContactResponse])
async def delete_contact(
    contact_id: UUID,
    tenant: TenantContextDependency,
    service: ContactServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONTACT_DELETE))],
) -> ApiResponse[ContactResponse]:
    row = await service.delete(tenant.tenant_id, contact_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Contact deleted successfully")
