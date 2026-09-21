"""Dunning rule and reminder log schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.common.schemas.filters import BaseFilter
from app.core.enums import DunningTemplateKey


class DunningRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    days_offset: int = Field(ge=-365, le=365)
    template_key: DunningTemplateKey
    escalate: bool = False
    description: str | None = None
    is_active: bool = True


class DunningRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    days_offset: int | None = Field(default=None, ge=-365, le=365)
    template_key: DunningTemplateKey | None = None
    escalate: bool | None = None
    description: str | None = None
    is_active: bool | None = None


class DunningRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    days_offset: int
    template_key: DunningTemplateKey
    escalate: bool
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None


class DunningRuleFilter(BaseFilter):
    is_active: bool | None = None


class DunningLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    sales_invoice_id: UUID
    dunning_rule_id: UUID
    dunning_rule_name: str | None = None
    channel: str
    recipient_email: str | None
    sent_at: datetime
    created_by: UUID | None = None


class SendPaymentReminderRequest(BaseModel):
    dunning_rule_id: UUID | None = None


class SendPaymentReminderResponse(BaseModel):
    dunning_log_id: UUID
    recipient_email: str
