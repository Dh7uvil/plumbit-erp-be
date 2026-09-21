"""Dunning rule routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import DUNNING_MANAGE, DUNNING_READ
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.erp.accounting.dunning.dependencies import DunningRuleServiceDependency
from app.erp.accounting.dunning.schemas import (
    DunningRuleCreate,
    DunningRuleFilter,
    DunningRuleResponse,
    DunningRuleUpdate,
)

router = APIRouter(prefix="/dunning-rules", tags=["Dunning Rules"])


@router.get("", response_model=ApiResponse[list[DunningRuleResponse]])
async def list_dunning_rules(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: DunningRuleServiceDependency,
    filters: Annotated[DunningRuleFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(DUNNING_READ))],
) -> ApiResponse[list[DunningRuleResponse]]:
    rows, total = await service.list(
        tenant.tenant_id, page=page, common_filter=filters, is_active=filters.is_active
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[DunningRuleResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_dunning_rule(
    payload: DunningRuleCreate,
    tenant: TenantContextDependency,
    service: DunningRuleServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DUNNING_MANAGE))],
) -> ApiResponse[DunningRuleResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Dunning rule created successfully")


@router.get("/{rule_id}", response_model=ApiResponse[DunningRuleResponse])
async def get_dunning_rule(
    rule_id: UUID,
    tenant: TenantContextDependency,
    service: DunningRuleServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DUNNING_READ))],
) -> ApiResponse[DunningRuleResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, rule_id))


@router.patch("/{rule_id}", response_model=ApiResponse[DunningRuleResponse])
async def update_dunning_rule(
    rule_id: UUID,
    payload: DunningRuleUpdate,
    tenant: TenantContextDependency,
    service: DunningRuleServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DUNNING_MANAGE))],
) -> ApiResponse[DunningRuleResponse]:
    row = await service.update(
        tenant.tenant_id, rule_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Dunning rule updated successfully")


@router.delete("/{rule_id}", response_model=ApiResponse[DunningRuleResponse])
async def delete_dunning_rule(
    rule_id: UUID,
    tenant: TenantContextDependency,
    service: DunningRuleServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DUNNING_MANAGE))],
) -> ApiResponse[DunningRuleResponse]:
    row = await service.delete(tenant.tenant_id, rule_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Dunning rule deleted successfully")
