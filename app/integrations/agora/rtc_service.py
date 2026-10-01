"""Agora RTC token minting backed by stable user identity mappings."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.calls.repository import CallParticipantRepository, CallRepository
from app.communication.shared.feature import require_communication_enabled
from app.communication.shared.rate_limit import enforce_token_rate_limit
from app.core.config import get_settings
from app.core.enums import CallStatus
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.integrations.agora.channels import validate_channel_name
from app.integrations.agora.identity import ChatIdentityService
from app.integrations.agora.tokens import build_rtc_token


class AgoraRTCService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.identity = ChatIdentityService(session)
        self.calls = CallRepository(session)
        self.participants = CallParticipantRepository(session)

    async def mint_token(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        channel_name: str,
        call_id: UUID,
    ) -> tuple[str, int, datetime]:
        require_communication_enabled()
        enforce_token_rate_limit(str(user_id))
        try:
            validate_channel_name(channel_name)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        mapping = await self.identity.get_or_create_mapping(tenant_id, user_id)
        await self._require_call_participant(
            tenant_id, call_id, user_id, channel_name=channel_name
        )

        settings = get_settings()
        token, expires = build_rtc_token(
            settings, channel=channel_name, uid=mapping.rtc_uid
        )
        return token, mapping.rtc_uid, expires

    async def refresh_token(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        channel_name: str,
        call_id: UUID,
    ) -> tuple[str, int, datetime]:
        return await self.mint_token(
            tenant_id,
            user_id,
            channel_name=channel_name,
            call_id=call_id,
        )

    async def _require_call_participant(
        self,
        tenant_id: UUID,
        call_id: UUID,
        user_id: UUID,
        *,
        channel_name: str,
    ) -> None:
        call = await self.calls.get(tenant_id, call_id)
        if call is None or call.channel_name != channel_name:
            raise ResourceNotFoundError("Call not found")
        if call.status in (
            CallStatus.ENDED.value,
            CallStatus.MISSED.value,
            CallStatus.REJECTED.value,
            CallStatus.CANCELLED.value,
        ):
            raise ValidationError("Call is no longer active")
        part = await self.participants.get(tenant_id, call_id, user_id)
        if part is None:
            raise ResourceNotFoundError("Call not found")
