"""Read-only utility scan routes."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.catalog import REPORT_LEDGER
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.erp.accounting.integrity.dependencies import GlIntegrityServiceDependency
from app.erp.accounting.integrity.schemas import GlIntegrityResponse

router = APIRouter(prefix="/utilities", tags=["Utilities"])


@router.get("/gl-integrity", response_model=ApiResponse[GlIntegrityResponse])
async def get_gl_integrity(
    tenant: TenantContextDependency,
    service: GlIntegrityServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_LEDGER))],
    as_of: Annotated[date | None, Query()] = None,
) -> ApiResponse[GlIntegrityResponse]:
    row = await service.scan(tenant.tenant_id, as_of=as_of)
    return ApiResponse(data=row)
