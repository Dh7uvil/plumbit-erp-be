"""Current-user table column preference routes."""

from typing import Annotated

from fastapi import APIRouter, Path

from app.common.dependencies.auth import CurrentUserDependency
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.common.table_preferences.dependencies import TablePreferenceServiceDependency
from app.common.table_preferences.schemas import TablePreferenceResponse, TablePreferenceUpdate

router = APIRouter(prefix="/users/me", tags=["Table Preferences"])

TableKeyPath = Annotated[
    str,
    Path(
        min_length=3,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$",
        description="Catalog key for a list table, e.g. erp.sales_orders",
    ),
]


@router.get(
    "/table-preferences/{table_key}",
    response_model=ApiResponse[TablePreferenceResponse],
    summary="Get table column preferences",
    description=(
        "Return the authenticated user's column visibility and order for a list table. "
        "Falls back to module defaults when no preference is saved."
    ),
)
async def get_table_preference(
    table_key: TableKeyPath,
    tenant: TenantContextDependency,
    current_user: CurrentUserDependency,
    service: TablePreferenceServiceDependency,
) -> ApiResponse[TablePreferenceResponse]:
    data = await service.get(
        tenant.tenant_id,
        tenant.user_id,
        table_key,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=data)


@router.put(
    "/table-preferences/{table_key}",
    response_model=ApiResponse[TablePreferenceResponse],
    summary="Save table column preferences",
)
async def put_table_preference(
    table_key: TableKeyPath,
    payload: TablePreferenceUpdate,
    tenant: TenantContextDependency,
    current_user: CurrentUserDependency,
    service: TablePreferenceServiceDependency,
) -> ApiResponse[TablePreferenceResponse]:
    data = await service.upsert(
        tenant.tenant_id,
        tenant.user_id,
        table_key,
        payload,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=data, message="Table columns saved")


@router.delete(
    "/table-preferences/{table_key}",
    response_model=ApiResponse[TablePreferenceResponse],
    summary="Reset table column preferences",
    description="Delete the saved preference so the table returns to module defaults.",
)
async def delete_table_preference(
    table_key: TableKeyPath,
    tenant: TenantContextDependency,
    current_user: CurrentUserDependency,
    service: TablePreferenceServiceDependency,
) -> ApiResponse[TablePreferenceResponse]:
    data = await service.reset(
        tenant.tenant_id,
        tenant.user_id,
        table_key,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=data, message="Table columns reset to default")
