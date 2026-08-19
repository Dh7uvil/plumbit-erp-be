"""Password hashing and typed JWT helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

import bcrypt
import jwt

from app.core.exceptions import InvalidTokenError, TokenExpiredError, TokenTypeError

MAX_BCRYPT_PASSWORD_BYTES = 72
DEFAULT_BCRYPT_ROUNDS = 12


class PasswordTooLongError(ValueError):
    """Raised when a password exceeds bcrypt's non-truncating byte limit."""


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """Validated claims shared by access and refresh tokens."""

    subject: str
    token_type: TokenType
    issued_at: datetime
    expires_at: datetime
    token_id: str
    tenant_id: str | None = None


def _password_bytes(password: str) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_BCRYPT_PASSWORD_BYTES:
        raise PasswordTooLongError("Password exceeds bcrypt's 72-byte UTF-8 limit")
    return encoded


def hash_password(
    password: str,
    *,
    rounds: int = DEFAULT_BCRYPT_ROUNDS,
) -> str:
    """Hash a password without bcrypt's unsafe silent truncation behavior."""

    if not 4 <= rounds <= 31:
        raise ValueError("bcrypt rounds must be between 4 and 31")
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt(rounds)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Safely verify a password; malformed hashes and oversized input fail closed."""

    try:
        password_bytes = _password_bytes(password)
        hash_bytes = password_hash.encode("ascii")
        return bcrypt.checkpw(password_bytes, hash_bytes)
    except (PasswordTooLongError, UnicodeEncodeError, ValueError):
        return False


def _create_token(
    *,
    subject: str,
    token_type: TokenType,
    secret: str,
    expires_delta: timedelta,
    tenant_id: str | None,
    algorithm: str,
    issuer: str | None,
    audience: str | None,
) -> str:
    if not subject:
        raise ValueError("Token subject must not be empty")
    if not secret:
        raise ValueError("JWT secret must not be empty")
    if expires_delta <= timedelta(0):
        raise ValueError("Token lifetime must be positive")

    issued_at = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": subject,
        "type": token_type.value,
        "iat": issued_at,
        "exp": issued_at + expires_delta,
        "jti": str(uuid4()),
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    if issuer is not None:
        payload["iss"] = issuer
    if audience is not None:
        payload["aud"] = audience

    return jwt.encode(payload, secret, algorithm=algorithm)


def create_access_token(
    *,
    subject: str,
    secret: str,
    expires_delta: timedelta,
    tenant_id: str | None = None,
    algorithm: str = "HS256",
    issuer: str | None = None,
    audience: str | None = None,
) -> str:
    return _create_token(
        subject=subject,
        token_type=TokenType.ACCESS,
        secret=secret,
        expires_delta=expires_delta,
        tenant_id=tenant_id,
        algorithm=algorithm,
        issuer=issuer,
        audience=audience,
    )


def create_refresh_token(
    *,
    subject: str,
    secret: str,
    expires_delta: timedelta,
    tenant_id: str | None = None,
    algorithm: str = "HS256",
    issuer: str | None = None,
    audience: str | None = None,
) -> str:
    return _create_token(
        subject=subject,
        token_type=TokenType.REFRESH,
        secret=secret,
        expires_delta=expires_delta,
        tenant_id=tenant_id,
        algorithm=algorithm,
        issuer=issuer,
        audience=audience,
    )


def _required_string(payload: dict[str, object], claim: str) -> str:
    value = payload.get(claim)
    if not isinstance(value, str) or not value:
        raise InvalidTokenError()
    return value


def _numeric_date(payload: dict[str, object], claim: str) -> datetime:
    value = payload.get(claim)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidTokenError()
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise InvalidTokenError() from exc


def decode_token(
    token: str,
    *,
    secret: str,
    expected_type: TokenType,
    algorithm: str = "HS256",
    issuer: str | None = None,
    audience: str | None = None,
) -> TokenClaims:
    """Decode, validate, and type-check a JWT without leaking library errors."""

    if not token or not secret:
        raise InvalidTokenError()

    try:
        payload: dict[str, object] = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            audience=audience,
            issuer=issuer,
            options={
                "require": ["sub", "type", "iat", "exp", "jti"],
                "verify_aud": audience is not None,
                "verify_iss": issuer is not None,
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError() from exc

    try:
        token_type = TokenType(_required_string(payload, "type"))
    except ValueError as exc:
        raise InvalidTokenError() from exc
    if token_type is not expected_type:
        raise TokenTypeError()

    tenant_id_value = payload.get("tenant_id")
    if tenant_id_value is not None and not isinstance(tenant_id_value, str):
        raise InvalidTokenError()

    return TokenClaims(
        subject=_required_string(payload, "sub"),
        token_type=token_type,
        issued_at=_numeric_date(payload, "iat"),
        expires_at=_numeric_date(payload, "exp"),
        token_id=_required_string(payload, "jti"),
        tenant_id=tenant_id_value,
    )


def decode_access_token(
    token: str,
    *,
    secret: str,
    algorithm: str = "HS256",
    issuer: str | None = None,
    audience: str | None = None,
) -> TokenClaims:
    return decode_token(
        token,
        secret=secret,
        expected_type=TokenType.ACCESS,
        algorithm=algorithm,
        issuer=issuer,
        audience=audience,
    )


def decode_refresh_token(
    token: str,
    *,
    secret: str,
    algorithm: str = "HS256",
    issuer: str | None = None,
    audience: str | None = None,
) -> TokenClaims:
    return decode_token(
        token,
        secret=secret,
        expected_type=TokenType.REFRESH,
        algorithm=algorithm,
        issuer=issuer,
        audience=audience,
    )
