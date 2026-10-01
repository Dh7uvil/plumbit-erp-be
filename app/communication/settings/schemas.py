"""Chat notification settings schemas."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatNotificationSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    message_notifications: bool
    group_notifications: bool
    call_notifications: bool
    sound_enabled: bool
    desktop_notifications: bool
    mobile_notifications: bool


class ChatNotificationSettingsUpdate(BaseModel):
    message_notifications: bool | None = None
    group_notifications: bool | None = None
    call_notifications: bool | None = None
    sound_enabled: bool | None = None
    desktop_notifications: bool | None = None
    mobile_notifications: bool | None = None
