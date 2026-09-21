"""Pipeline routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    PIPELINE_CREATE,
    PIPELINE_DELETE,
    PIPELINE_READ,
    PIPELINE_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.crm.pipelines.dependencies import PipelineServiceDependency
from app.crm.pipelines.schemas import (
    PipelineCreate,
    PipelineFilter,
    PipelineListItemResponse,
    PipelineResponse,
    PipelineStageCreate,
    PipelineStageResponse,
    PipelineStageUpdate,
    PipelineUpdate,
)

router = APIRouter(prefix="/pipelines", tags=["Pipelines"])


@router.get("", response_model=ApiResponse[list[PipelineListItemResponse]])
async def list_pipelines(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: PipelineServiceDependency,
    filters: Annotated[PipelineFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PIPELINE_READ))],
) -> ApiResponse[list[PipelineListItemResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
        is_default=filters.is_default,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[PipelineResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_pipeline(
    payload: PipelineCreate,
    tenant: TenantContextDependency,
    service: PipelineServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PIPELINE_CREATE))],
) -> ApiResponse[PipelineResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Pipeline created successfully")


@router.get("/{pipeline_id}", response_model=ApiResponse[PipelineResponse])
async def get_pipeline(
    pipeline_id: UUID,
    tenant: TenantContextDependency,
    service: PipelineServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PIPELINE_READ))],
) -> ApiResponse[PipelineResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, pipeline_id))


@router.patch("/{pipeline_id}", response_model=ApiResponse[PipelineResponse])
async def update_pipeline(
    pipeline_id: UUID,
    payload: PipelineUpdate,
    tenant: TenantContextDependency,
    service: PipelineServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PIPELINE_UPDATE))],
) -> ApiResponse[PipelineResponse]:
    row = await service.update(
        tenant.tenant_id, pipeline_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Pipeline updated successfully")


@router.delete("/{pipeline_id}", response_model=ApiResponse[PipelineResponse])
async def delete_pipeline(
    pipeline_id: UUID,
    tenant: TenantContextDependency,
    service: PipelineServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PIPELINE_DELETE))],
) -> ApiResponse[PipelineResponse]:
    row = await service.delete(tenant.tenant_id, pipeline_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Pipeline deleted successfully")


@router.post(
    "/{pipeline_id}/stages",
    response_model=ApiResponse[PipelineStageResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_pipeline_stage(
    pipeline_id: UUID,
    payload: PipelineStageCreate,
    tenant: TenantContextDependency,
    service: PipelineServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PIPELINE_UPDATE))],
) -> ApiResponse[PipelineStageResponse]:
    row = await service.create_stage(
        tenant.tenant_id, pipeline_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Pipeline stage created successfully")


@router.patch(
    "/{pipeline_id}/stages/{stage_id}",
    response_model=ApiResponse[PipelineStageResponse],
)
async def update_pipeline_stage(
    pipeline_id: UUID,
    stage_id: UUID,
    payload: PipelineStageUpdate,
    tenant: TenantContextDependency,
    service: PipelineServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PIPELINE_UPDATE))],
) -> ApiResponse[PipelineStageResponse]:
    row = await service.update_stage(
        tenant.tenant_id,
        pipeline_id,
        stage_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=row, message="Pipeline stage updated successfully")


@router.delete(
    "/{pipeline_id}/stages/{stage_id}",
    response_model=ApiResponse[PipelineStageResponse],
)
async def delete_pipeline_stage(
    pipeline_id: UUID,
    stage_id: UUID,
    tenant: TenantContextDependency,
    service: PipelineServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PIPELINE_UPDATE))],
) -> ApiResponse[PipelineStageResponse]:
    row = await service.delete_stage(
        tenant.tenant_id, pipeline_id, stage_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Pipeline stage deleted successfully")
