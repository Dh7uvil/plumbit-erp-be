"""Email message shapes for the SES adapter."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmailMessage(BaseModel):
    """Rendered email ready for delivery."""

    to: str = Field(min_length=3, max_length=255)
    subject: str = Field(min_length=1, max_length=998)
    text_body: str = Field(min_length=1)
    html_body: str | None = None
    reply_to: str | None = Field(default=None, max_length=255)
