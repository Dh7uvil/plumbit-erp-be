"""Safe identifier and token generators."""

import secrets
from uuid import UUID, uuid4


def generate_uuid() -> UUID:
    """Generate a random UUID for non-database identifiers."""

    return uuid4()


def generate_request_id() -> str:
    """Generate an opaque request correlation identifier."""

    return str(uuid4())


def generate_secure_token(*, entropy_bytes: int = 32) -> str:
    """Generate a URL-safe cryptographic token."""

    if entropy_bytes < 16:
        msg = "entropy_bytes must be at least 16"
        raise ValueError(msg)
    return secrets.token_urlsafe(entropy_bytes)
