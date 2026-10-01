"""Rate limiting for communication endpoints."""

from app.core.config import get_settings
from app.core.exceptions import RateLimitExceededError
from app.core.rate_limit import SlidingWindowLimiter, get_auth_limiter

_comm_limiter = SlidingWindowLimiter()

MESSAGE_LIMIT = 60
CALL_CREATE_LIMIT = 10
TYPING_LIMIT = 30
TOKEN_LIMIT = 20
REACTION_LIMIT = 120
SEARCH_LIMIT = 30
UPLOAD_LIMIT = 20


def _enforce(key: str, *, limit: int) -> None:
    settings = get_settings()
    if settings.env == "testing":
        return
    limiter = get_auth_limiter() if settings.redis_url else _comm_limiter
    allowed = limiter.hit(
        key,
        limit=limit,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if not allowed:
        raise RateLimitExceededError()


def enforce_message_rate_limit(user_id: str) -> None:
    _enforce(f"comm:message:{user_id}", limit=MESSAGE_LIMIT)


def enforce_call_create_rate_limit(user_id: str) -> None:
    _enforce(f"comm:call:{user_id}", limit=CALL_CREATE_LIMIT)


def enforce_typing_rate_limit(user_id: str, conversation_id: str) -> None:
    _enforce(f"comm:typing:{user_id}:{conversation_id}", limit=TYPING_LIMIT)


def enforce_token_rate_limit(user_id: str) -> None:
    _enforce(f"comm:token:{user_id}", limit=TOKEN_LIMIT)


def enforce_reaction_rate_limit(user_id: str) -> None:
    _enforce(f"comm:reaction:{user_id}", limit=REACTION_LIMIT)


def enforce_search_rate_limit(user_id: str) -> None:
    _enforce(f"comm:search:{user_id}", limit=SEARCH_LIMIT)


def enforce_upload_rate_limit(user_id: str) -> None:
    _enforce(f"comm:upload:{user_id}", limit=UPLOAD_LIMIT)
