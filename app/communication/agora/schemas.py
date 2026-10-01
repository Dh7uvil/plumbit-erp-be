"""Agora token and webhook schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RtcTokenRequest(BaseModel):
    channel_name: str = Field(min_length=1, max_length=64)
    call_id: UUID


class RtcTokenResponse(BaseModel):
    token: str
    rtc_uid: int
    channel_name: str
    expires_at: datetime


class AgoraWebhookAck(BaseModel):
    received: bool = True
