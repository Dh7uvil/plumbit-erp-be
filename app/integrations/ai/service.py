"""AI assistant use cases: audit logging and read-only suggestion generation."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from uuid import UUID

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.mixins import TenantScopedMixin, UUIDPrimaryKeyMixin
from app.db.session import transaction
from app.integrations.ai.schemas import (
    AiAssistRequest,
    AiAssistResponse,
    AiContextEntity,
    AiSuggestion,
)

logger = logging.getLogger(__name__)

_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
_OPENAI_MODEL = "gpt-4o-mini"
_READ_ONLY_SYSTEM_PROMPT = (
    "You are a read-only ERP assistant for Plumbit ERP. "
    "Provide concise, actionable suggestions only. "
    "Never instruct the user to post journals, adjust stock, or mutate data automatically. "
    "Respond as JSON: {\"suggestions\": [{\"title\": str, \"body\": str}, ...]} with 1-3 items."
)


class AiRequest(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    """Audit log row for every AI assistant invocation."""

    __tablename__ = "ai_requests"

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    context_entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    context_entity_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    response_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AiAssistantService:
    """Generate read-only suggestions and persist an audit row per request."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def assist(
        self,
        tenant_id: UUID,
        user_id: UUID,
        payload: AiAssistRequest,
    ) -> AiAssistResponse:
        context = payload.context
        provider, suggestions = await self._generate_suggestions(payload.prompt, context)
        response = AiAssistResponse(
            suggestions=suggestions,
            provider=provider,
            read_only=True,
            request_id=UUID(int=0),
        )

        async with transaction(self.session):
            row = AiRequest(
                tenant_id=tenant_id,
                user_id=user_id,
                prompt=payload.prompt,
                context_entity_type=context.entity_type if context else None,
                context_entity_id=context.entity_id if context else None,
                provider=provider,
                response_json={"suggestions": [item.model_dump() for item in suggestions]},
            )
            self.session.add(row)
            await self.session.flush()
            response = response.model_copy(update={"request_id": row.id})

        return response

    async def _generate_suggestions(
        self,
        prompt: str,
        context: AiContextEntity | None,
    ) -> tuple[str, list[AiSuggestion]]:
        api_key = (
            self.settings.openai_api_key.get_secret_value()
            if self.settings.openai_api_key is not None
            else None
        )
        if api_key:
            try:
                suggestions = await asyncio.to_thread(
                    _call_openai,
                    api_key,
                    prompt,
                    context,
                )
                return "openai", suggestions
            except Exception:
                logger.exception("openai_assist_failed")
        return "stub", _stub_suggestions(prompt, context)


def _stub_suggestions(prompt: str, context: AiContextEntity | None) -> list[AiSuggestion]:
    context_hint = ""
    if context and context.entity_type:
        context_hint = f" Context: {context.entity_type}"
        if context.entity_id:
            context_hint += f" ({context.entity_id})."

    return [
        AiSuggestion(
            title="Read-only guidance",
            body=(
                f"You asked: {prompt.strip()}.{context_hint} "
                "This assistant returns suggestions only and cannot post to the ledger or stock."
            ),
        ),
        AiSuggestion(
            title="Suggested next steps",
            body=(
                "Open the relevant ERP screen, verify permissions and document status, "
                "then perform any required actions manually."
            ),
        ),
    ]


def _call_openai(
    api_key: str,
    prompt: str,
    context: AiContextEntity | None,
) -> list[AiSuggestion]:
    user_content = prompt.strip()
    if context and (context.entity_type or context.entity_id):
        user_content += "\n\nContext entity:"
        if context.entity_type:
            user_content += f" type={context.entity_type}"
        if context.entity_id:
            user_content += f" id={context.entity_id}"

    payload = {
        "model": _OPENAI_MODEL,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _READ_ONLY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }
    request = urllib.request.Request(
        _OPENAI_CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail}") from exc

    content = body["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    raw_items = parsed.get("suggestions")
    if not isinstance(raw_items, list) or not raw_items:
        raise RuntimeError("OpenAI response missing suggestions")

    suggestions: list[AiSuggestion] = []
    for item in raw_items[:3]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "Suggestion")).strip() or "Suggestion"
        body_text = str(item.get("body", "")).strip()
        if body_text:
            suggestions.append(AiSuggestion(title=title[:200], body=body_text[:8000]))
    if not suggestions:
        raise RuntimeError("OpenAI returned no usable suggestions")
    return suggestions
