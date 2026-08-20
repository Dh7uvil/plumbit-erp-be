"""Request context propagation and structured access logging."""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from time import perf_counter
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = b"x-request-id"
FORWARDED_FOR_HEADER = b"x-forwarded-for"
REAL_IP_HEADER = b"x-real-ip"
USER_AGENT_HEADER = b"user-agent"

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_context: ContextVar[str | None] = ContextVar("tenant_id", default=None)
user_id_context: ContextVar[str | None] = ContextVar("user_id", default=None)
client_ip_context: ContextVar[str | None] = ContextVar("client_ip", default=None)
user_agent_context: ContextVar[str | None] = ContextVar("user_agent", default=None)

access_logger = logging.getLogger("app.access")


def get_request_id() -> str | None:
    return request_id_context.get()


def get_tenant_id() -> str | None:
    return tenant_id_context.get()


def get_user_id() -> str | None:
    return user_id_context.get()


def set_tenant_id(tenant_id: str | None) -> Token[str | None]:
    """Set the authenticated tenant context for the current request."""

    return tenant_id_context.set(tenant_id)


def set_user_id(user_id: str | None) -> Token[str | None]:
    """Set the authenticated user context for the current request."""

    return user_id_context.set(user_id)


def get_client_ip() -> str | None:
    return client_ip_context.get()


def get_user_agent() -> str | None:
    return user_agent_context.get()


def _header_value(headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    for key, value in headers:
        if key.lower() == name:
            decoded = value.decode("latin-1", errors="replace").strip()
            return decoded or None
    return None


def _client_ip_from_scope(scope: Scope) -> str | None:
    headers = list(scope.get("headers") or [])
    forwarded = _header_value(headers, FORWARDED_FOR_HEADER)
    if forwarded:
        first_hop = forwarded.split(",", 1)[0].strip()
        if first_hop:
            return first_hop
    real_ip = _header_value(headers, REAL_IP_HEADER)
    if real_ip:
        return real_ip
    client = scope.get("client")
    if isinstance(client, (tuple, list)) and client:
        host = client[0]
        if isinstance(host, str) and host:
            return host
    return None


class RequestContextMiddleware:
    """Set request context, return a request ID, and emit one access log."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
        request_token = request_id_context.set(request_id)
        tenant_token = tenant_id_context.set(None)
        user_token = user_id_context.set(None)
        client_ip_token = client_ip_context.set(_client_ip_from_scope(scope))
        user_agent_token = user_agent_context.set(
            _header_value(list(scope.get("headers") or []), USER_AGENT_HEADER)
        )
        started_at = perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER, request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = round((perf_counter() - started_at) * 1000, 3)
            access_logger.info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "tenant_id": tenant_id_context.get(),
                    "user_id": user_id_context.get(),
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status_code": status_code,
                    "duration": duration_ms,
                },
            )
            user_agent_context.reset(user_agent_token)
            client_ip_context.reset(client_ip_token)
            user_id_context.reset(user_token)
            tenant_id_context.reset(tenant_token)
            request_id_context.reset(request_token)
