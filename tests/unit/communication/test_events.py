"""Realtime event envelope tests."""

from uuid import UUID

from app.integrations.agora.events import RealtimeEvent, truncate_event_json


def test_envelope_truncation() -> None:
    payload = {
        "v": 1,
        "type": "message.created",
        "tenant_id": str(UUID(int=1)),
        "data": {"body": "x" * 50_000},
        "truncated": False,
    }
    encoded = truncate_event_json(payload)
    assert len(encoded.encode("utf-8")) <= 32 * 1024
    assert "truncated" in encoded


def test_realtime_event_to_json() -> None:
    event = RealtimeEvent(type="typing.started", data={"is_typing": True})
    assert "typing.started" in event.to_json()
