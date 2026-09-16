"""Request and response schemas for user notification preferences."""

from pydantic import BaseModel, ConfigDict


class NotificationPreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email_enabled: bool | None = None
    in_app_enabled: bool | None = None
    whatsapp_enabled: bool | None = None


class NotificationPreferenceResponse(BaseModel):
    email_enabled: bool
    in_app_enabled: bool
    whatsapp_enabled: bool
    is_default: bool
