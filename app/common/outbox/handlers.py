"""Outbox handler registry. Unknown event types must never be marked DONE."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.common.outbox.models import OutboxEvent

OutboxHandler = Callable[[OutboxEvent], Awaitable[None]]

_HANDLERS: dict[str, OutboxHandler] = {}


def register(event_type: str, handler: OutboxHandler) -> None:
    """Register or replace the handler for ``event_type``."""

    _HANDLERS[event_type] = handler


def get_handler(event_type: str) -> OutboxHandler | None:
    return _HANDLERS.get(event_type)


def clear() -> None:
    """Remove every handler. Intended for tests."""

    _HANDLERS.clear()
