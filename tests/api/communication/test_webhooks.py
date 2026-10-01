"""Agora webhook API tests."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_agora_webhook_invalid_signature(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setenv("AGORA_WEBHOOK_SECRET", "test-webhook-secret")
    from app.core.config import get_settings

    get_settings.cache_clear()

    body = json.dumps({"noticeId": "n1", "eventType": 107, "payload": {}}).encode()
    response = await client.post(
        "/api/v1/communication/agora/webhooks",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Agora-Signature-V2": "invalid",
        },
    )
    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_agora_webhook_valid_signature_records_event(
    client: AsyncClient, monkeypatch
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setenv("AGORA_WEBHOOK_SECRET", secret)
    from app.core.config import get_settings

    get_settings.cache_clear()

    body_dict = {
        "noticeId": "notice-duplicate-test",
        "eventType": 107,
        "payload": {"channelName": "missing-channel", "uid": 1},
    }
    body = json.dumps(body_dict).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    response = await client.post(
        "/api/v1/communication/agora/webhooks",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Agora-Signature-V2": signature,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["received"] is True
