"""Recurring template routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from app.auth.catalog import (
    RECURRING_CREATE,
    RECURRING_DELETE,
    RECURRING_GENERATE,
    RECURRING_READ,
    RECURRING_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.core.config import get_settings
from app.erp.accounting.recurring.dependencies import RecurringServiceDependency
from app.erp.accounting.recurring.schemas import (
    RecurringTemplateCreate,
    RecurringTemplateFilter,
    RecurringTemplateResponse,
    RecurringTemplateUpdate,
)
from app.erp.accounting.recurring.worker import enqueue_due_recurring

router = APIRouter(prefix="/recurring-templates", tags=["Recurring Templates"])
IfMatch = Annotated[str | None, Header(alias="If-Match")]


@router.get("", response_model=ApiResponse[list[RecurringTemplateResponse]])
async def list_recurring_templates(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: RecurringServiceDependency,
    filters: Annotated[RecurringTemplateFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(RECURRING_READ))],
) -> ApiResponse[list[RecurringTemplateResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        document_kind=filters.document_kind.value if filters.document_kind else None,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[RecurringTemplateResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_recurring_template(
    payload: RecurringTemplateCreate,
    tenant: TenantContextDependency,
    service: RecurringServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(RECURRING_CREATE))],
) -> ApiResponse[RecurringTemplateResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Recurring template created successfully")


@router.post("/run-due", response_model=ApiResponse[dict[str, int]])
async def run_due_recurring_templates(
    tenant: TenantContextDependency,
    service: RecurringServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(RECURRING_GENERATE))],
) -> ApiResponse[dict[str, int]]:
    if get_settings().feature_background_workers_enabled:
        queued = await enqueue_due_recurring()
        return ApiResponse(data={"queued": queued}, message="Due templates queued")
    generated = await service.run_due(tenant.tenant_id, actor_user_id=tenant.user_id)
    return ApiResponse(data={"generated": generated}, message="Due drafts generated")


@router.get("/{template_id}", response_model=ApiResponse[RecurringTemplateResponse])
async def get_recurring_template(
    template_id: UUID,
    tenant: TenantContextDependency,
    service: RecurringServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(RECURRING_READ))],
) -> ApiResponse[RecurringTemplateResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, template_id))


@router.patch("/{template_id}", response_model=ApiResponse[RecurringTemplateResponse])
async def update_recurring_template(
    template_id: UUID,
    payload: RecurringTemplateUpdate,
    tenant: TenantContextDependency,
    service: RecurringServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(RECURRING_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[RecurringTemplateResponse]:
    expected = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.update(
        tenant.tenant_id,
        template_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=expected,
    )
    return ApiResponse(data=row, message="Recurring template updated successfully")


@router.delete("/{template_id}", response_model=ApiResponse[RecurringTemplateResponse])
async def delete_recurring_template(
    template_id: UUID,
    tenant: TenantContextDependency,
    service: RecurringServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(RECURRING_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[RecurringTemplateResponse]:
    expected = require_document_version(if_match=if_match)
    row = await service.delete(
        tenant.tenant_id, template_id, actor_user_id=tenant.user_id, expected_version=expected
    )
    return ApiResponse(data=row, message="Recurring template deleted successfully")


@router.post("/{template_id}/generate", response_model=ApiResponse[RecurringTemplateResponse])
async def generate_recurring_draft(
    template_id: UUID,
    tenant: TenantContextDependency,
    service: RecurringServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(RECURRING_GENERATE))],
) -> ApiResponse[RecurringTemplateResponse]:
    row = await service.materialize(
        tenant.tenant_id, template_id, actor_user_id=tenant.user_id, force=True
    )
    return ApiResponse(data=row, message="Draft generated successfully")
