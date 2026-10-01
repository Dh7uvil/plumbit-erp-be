"""WebSocket realtime gateway routes."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import PRESENCE_READ
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.communication.conversations.service import ConversationService
from app.communication.realtime.connection_manager import get_connection_manager
from app.communication.realtime.tickets import WsTicketPayload, consume_ws_ticket, create_ws_ticket
from app.communication.shared.feature import require_communication_enabled
from app.communication.shared.rate_limit import enforce_typing_rate_limit
from app.communication.shared.signaling_publisher import build_event
from app.core.enums import PresenceStatus
from app.db.session import get_db
from app.integrations.agora.channels import (
    conversation_channel_name,
    inbox_channel_name,
    parse_conversation_channel,
    presence_channel_name,
)
from app.integrations.agora.signaling import get_signaling_client
from app.integrations.realtime.presence import get_presence_connection_store
from app.auth.repository import AccessRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Communication"])


class WsTicketResponse(BaseModel):
    ticket: str = Field(min_length=1)
    expires_in_seconds: int = 60


async def _emit_presence_changed(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    status: PresenceStatus,
) -> None:
    from app.communication.presence.repository import PresenceRepository
    from app.communication.shared.signaling_publisher import (
        flush_pending_signaling,
        schedule_signaling_event,
    )
    from app.common.utils.datetime import utcnow

    repo = PresenceRepository(session)
    row = await repo.get(tenant_id, user_id)
    now = utcnow()
    custom_status = row.custom_status if row is not None else None
    last_seen_at = (row.last_seen_at or now).isoformat() if row is not None else now.isoformat()
    schedule_signaling_event(
        session,
        build_event(
            event_type="presence.changed",
            tenant_id=tenant_id,
            actor_id=user_id,
            data={
                "user_id": str(user_id),
                "status": status.value,
                "custom_status": custom_status,
                "last_seen_at": last_seen_at,
            },
        ),
    )
    await flush_pending_signaling(session)


@router.post("/ws/ticket", response_model=ApiResponse[WsTicketResponse])
async def mint_ws_ticket(
    tenant: TenantContextDependency,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission(PRESENCE_READ))],
) -> ApiResponse[WsTicketResponse]:
    require_communication_enabled()
    user = await AccessRepository(session).get_user_by_id(tenant.user_id)
    token_version = user.token_version if user is not None else 0
    ticket = await create_ws_ticket(
        user_id=tenant.user_id,
        tenant_id=tenant.tenant_id,
        token_version=token_version,
    )
    return ApiResponse(data=WsTicketResponse(ticket=ticket))


@router.websocket("/ws")
async def communication_websocket(
    websocket: WebSocket,
    ticket: str,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    require_communication_enabled()
    payload = await consume_ws_ticket(ticket)
    if payload is None:
        await websocket.close(code=4401)
        return

    user = await AccessRepository(session).get_user_by_id(payload.user_id)
    if user is None or user.token_version != payload.token_version:
        await websocket.close(code=4401)
        return

    manager = get_connection_manager()
    conn_id = uuid4().hex
    await manager.register(websocket, conn_id, payload)

    inbox = inbox_channel_name(payload.user_id)
    presence = presence_channel_name(payload.tenant_id)
    await manager.subscribe(conn_id, inbox)
    await manager.subscribe(conn_id, presence)

    presence_store = get_presence_connection_store()
    _, became_online = await presence_store.increment(payload.tenant_id, payload.user_id)
    if became_online:
        await _emit_presence_changed(
            session,
            tenant_id=payload.tenant_id,
            user_id=payload.user_id,
            status=PresenceStatus.ONLINE,
        )

    conversation_service = ConversationService(session)
    signaling = get_signaling_client()

    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                continue
            op = message.get("op")
            if op == "ping":
                await presence_store.refresh(payload.tenant_id, payload.user_id)
                await manager.send_json(conn_id, {"op": "pong"})
                continue
            if op == "subscribe":
                channel = message.get("channel")
                if not isinstance(channel, str):
                    continue
                parsed = parse_conversation_channel(channel)
                if parsed is not None:
                    tenant_prefix, conversation_id = parsed
                    if tenant_prefix != payload.tenant_id.hex[:8]:
                        await manager.send_json(
                            conn_id,
                            {"op": "error", "message": "Forbidden channel"},
                        )
                        continue
                    try:
                        await conversation_service.require_participant(
                            payload.tenant_id,
                            conversation_id,
                            payload.user_id,
                        )
                    except Exception:  # noqa: BLE001
                        await manager.send_json(
                            conn_id,
                            {"op": "error", "message": "Forbidden channel"},
                        )
                        continue
                await manager.subscribe(conn_id, channel)
                await manager.send_json(conn_id, {"op": "subscribed", "channel": channel})
                continue
            if op == "unsubscribe":
                channel = message.get("channel")
                if isinstance(channel, str):
                    await manager.unsubscribe(conn_id, channel)
                continue
            if op == "typing":
                conversation_id_raw = message.get("conversation_id")
                is_typing = message.get("is_typing")
                if not isinstance(conversation_id_raw, str) or not isinstance(is_typing, bool):
                    continue
                try:
                    conversation_id = UUID(conversation_id_raw)
                except ValueError:
                    continue
                enforce_typing_rate_limit(str(payload.user_id), str(conversation_id))
                await conversation_service.require_participant(
                    payload.tenant_id,
                    conversation_id,
                    payload.user_id,
                )
                event = build_event(
                    event_type="typing.started" if is_typing else "typing.stopped",
                    tenant_id=payload.tenant_id,
                    actor_id=payload.user_id,
                    conversation_id=conversation_id,
                )
                channel = conversation_channel_name(payload.tenant_id, conversation_id)
                await signaling.publish(
                    channel=channel,
                    sender_id=str(payload.user_id),
                    event=event,
                )
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.warning("WebSocket session error conn=%s", conn_id, exc_info=True)
    finally:
        await manager.disconnect(conn_id)
        _, became_offline = await presence_store.decrement(payload.tenant_id, payload.user_id)
        if became_offline:
            await _emit_presence_changed(
                session,
                tenant_id=payload.tenant_id,
                user_id=payload.user_id,
                status=PresenceStatus.OFFLINE,
            )
