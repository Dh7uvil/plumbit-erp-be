"""Token minting wrappers for Agora RTC."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.integrations.agora.rtc_token_builder2 import Role_Publisher, RtcTokenBuilder


def build_rtc_token(
    settings: Settings,
    *,
    channel: str,
    uid: int,
    role: int = Role_Publisher,
) -> tuple[str, datetime]:
    if not settings.agora_app_id or not settings.agora_app_certificate:
        return "", datetime.now(timezone.utc)
    ttl = settings.agora_rtc_token_ttl_seconds
    token = RtcTokenBuilder.build_token_with_uid(
        settings.agora_app_id,
        settings.agora_app_certificate.get_secret_value(),
        channel,
        uid,
        role,
        ttl,
        ttl,
    )
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    return token, expires_at
