"""Agora Notification Center Service webhook helpers."""

from __future__ import annotations

import hashlib
import hmac


def verify_agora_webhook_signature(
    body: bytes,
    signature_v2: str | None,
    secret: str,
) -> bool:
    if not signature_v2:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_v2)
