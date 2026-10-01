"""Direct conversation idempotency key."""

from uuid import UUID


def build_direct_key(user_a: UUID, user_b: UUID) -> str:
    low, high = sorted((user_a, user_b), key=lambda value: str(value))
    return f"{low}:{high}"
