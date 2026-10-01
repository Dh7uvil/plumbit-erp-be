"""Communication search routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.catalog import CONVERSATION_READ, MESSAGE_READ
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.communication.messages.schemas import MessageResponse
from app.communication.search.dependencies import SearchServiceDependency
from app.communication.search.schemas import SearchResponse, SearchType
from app.communication.shared.feature import require_communication_enabled
from app.communication.shared.rate_limit import enforce_search_rate_limit

router = APIRouter(tags=["Communication"])


@router.get("/search", response_model=ApiResponse[SearchResponse])
async def search(
    tenant: TenantContextDependency,
    service: SearchServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_READ))],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    type: Annotated[SearchType, Query(alias="type")],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ApiResponse[SearchResponse]:
    require_communication_enabled()
    enforce_search_rate_limit(str(tenant.user_id))
    data = await service.search(
        tenant.tenant_id,
        tenant.user_id,
        q=q,
        search_type=type,
        limit=limit,
    )
    return ApiResponse(data=data)


@router.get(
    "/conversations/{conversation_id}/messages/search",
    response_model=ApiResponse[list[MessageResponse]],
)
async def search_conversation_messages(
    conversation_id: UUID,
    tenant: TenantContextDependency,
    service: SearchServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MESSAGE_READ))],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ApiResponse[list[MessageResponse]]:
    require_communication_enabled()
    enforce_search_rate_limit(str(tenant.user_id))
    rows = await service.search_conversation_messages(
        tenant.tenant_id,
        conversation_id,
        tenant.user_id,
        q=q,
        limit=limit,
    )
    return ApiResponse(data=rows)
