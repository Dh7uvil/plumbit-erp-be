"""Agora token and webhook routes."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import CALL_JOIN
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.communication.agora.dependencies import AgoraRTCServiceDependency
from app.communication.agora.schemas import (
    AgoraWebhookAck,
    RtcTokenRequest,
    RtcTokenResponse,
)
from app.communication.agora.webhook_service import AgoraWebhookService
from app.db.session import get_db
from app.communication.shared.feature import require_communication_enabled
from app.core.config import get_settings
from app.core.exceptions import InvalidCredentialsError
from app.integrations.agora.webhooks import verify_agora_webhook_signature

router = APIRouter(prefix="/agora", tags=["Communication"])


@router.post("/rtc-token", response_model=ApiResponse[RtcTokenResponse])
async def mint_rtc_token(
    payload: RtcTokenRequest,
    tenant: TenantContextDependency,
    service: AgoraRTCServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CALL_JOIN))],
) -> ApiResponse[RtcTokenResponse]:
    require_communication_enabled()
    token, rtc_uid, expires_at = await service.mint_token(
        tenant.tenant_id,
        tenant.user_id,
        channel_name=payload.channel_name,
        call_id=payload.call_id,
    )
    return ApiResponse(
        data=RtcTokenResponse(
            token=token,
            rtc_uid=rtc_uid,
            channel_name=payload.channel_name,
            expires_at=expires_at,
        )
    )


@router.post("/webhooks", response_model=ApiResponse[AgoraWebhookAck])
async def agora_webhooks(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AgoraWebhookAck]:
    raw_body = await request.body()
    settings = get_settings()
    secret = settings.agora_webhook_secret
    if secret is not None:
        signature = request.headers.get("Agora-Signature-V2")
        if not verify_agora_webhook_signature(
            raw_body,
            signature,
            secret.get_secret_value(),
        ):
            raise InvalidCredentialsError()
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        body = None
    if isinstance(body, dict):
        await AgoraWebhookService(session).process(body)
    return ApiResponse(data=AgoraWebhookAck())
