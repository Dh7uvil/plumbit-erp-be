"""Tenant colleague directory for chat participant pickers."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import CONVERSATION_READ
from app.auth.models import User
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.communication.colleagues.schemas import ColleagueResponse
from app.communication.shared.feature import require_communication_enabled
from app.db.session import get_db

router = APIRouter(tags=["Communication"])

_CHAT_ELIGIBLE_STATUSES = ("ACTIVE", "INVITED")


@router.get("/colleagues", response_model=ApiResponse[list[ColleagueResponse]])
async def list_colleagues(
    tenant: TenantContextDependency,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_READ))],
) -> ApiResponse[list[ColleagueResponse]]:
    """List chat-eligible users in the tenant without requiring identity.user.read."""
    require_communication_enabled()
    stmt = (
        select(User)
        .where(
            User.tenant_id == tenant.tenant_id,
            User.status.in_(_CHAT_ELIGIBLE_STATUSES),
        )
        .order_by(User.name.asc())
    )
    result = await session.execute(stmt)
    rows = [
        ColleagueResponse.model_validate(user)
        for user in result.scalars().all()
        if user.id != tenant.user_id
    ]
    return ApiResponse(data=rows)
