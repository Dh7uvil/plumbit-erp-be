"""AI assistant HTTP routes."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import AI_ASSISTANT_USE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.core.config import get_settings
from app.core.exceptions import ResourceNotFoundError
from app.db.session import get_db
from app.integrations.ai.schemas import AiAssistRequest, AiAssistResponse
from app.integrations.ai.service import AiAssistantService

router = APIRouter(prefix="/ai", tags=["AI Assistant"])


def get_ai_assistant_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AiAssistantService:
    return AiAssistantService(session)


AiAssistantServiceDependency = Annotated[AiAssistantService, Depends(get_ai_assistant_service)]


@router.post(
    "/assist",
    response_model=ApiResponse[AiAssistResponse],
    summary="Get read-only AI suggestions",
    description=(
        "Returns structured, read-only guidance for a prompt. "
        "Every request is logged in ai_requests. "
        "Never posts to ledger or stock."
    ),
)
async def assist(
    payload: AiAssistRequest,
    tenant: TenantContextDependency,
    _: Annotated[CurrentUser, Depends(require_permission(AI_ASSISTANT_USE))],
    service: AiAssistantServiceDependency,
) -> ApiResponse[AiAssistResponse]:
    if not get_settings().feature_ai_assistant_enabled:
        raise ResourceNotFoundError("AI assistant is not enabled")

    data = await service.assist(tenant.tenant_id, tenant.user_id, payload)
    return ApiResponse(data=data)
