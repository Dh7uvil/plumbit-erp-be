"""Centralized, environment-backed application configuration."""

import os
from functools import lru_cache
from typing import Annotated, Any, Literal
from urllib.parse import quote

from pydantic import AnyHttpUrl, Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _settings_env_file() -> str:
    """Prefer `.env.test` when the process is already marked as testing."""

    if os.environ.get("ENV", "").strip().lower() == "testing":
        return ".env.test"
    return ".env"


class Settings(BaseSettings):
    """Validated settings loaded from environment variables and an optional local `.env` file."""

    model_config = SettingsConfigDict(
        env_file=_settings_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    # Application
    env: Literal["development", "testing", "staging", "production"] = "development"
    app_name: str = "Plumbit ERP API"
    app_version: str = "0.1.0"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_v1_prefix: str = "/api/v1"

    # Database
    database_host: str
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str
    database_user: str
    database_password: SecretStr
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=20, ge=0)
    database_pool_timeout_seconds: int = Field(default=30, ge=1)
    database_pool_recycle_seconds: int = Field(default=1800, ge=1)

    # Authentication / JWT
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_access_token_ttl_minutes: int = Field(default=30, ge=1)
    jwt_refresh_token_ttl_minutes: int = Field(default=10_080, ge=1)

    # CORS
    cors_origins: Annotated[list[AnyHttpUrl], NoDecode] = Field(default_factory=list)

    # Rate limiting
    rate_limit_requests: int = Field(default=100, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    auth_rate_limit_requests: int = Field(default=10, ge=1)

    # Uploads
    max_upload_size_mb: int = Field(default=25, ge=1)
    allowed_upload_mime_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "text/csv",
            "application/json",
            "application/pdf",
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "application/msword",
            "application/vnd.ms-excel",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ]
    )

    # Redis
    redis_url: str | None = None

    # AWS / S3
    aws_region: str | None = None
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    s3_bucket_name: str | None = None
    s3_endpoint_url: AnyHttpUrl | None = None
    s3_presign_ttl_seconds: int = Field(default=300, ge=1, le=86_400)

    # Amazon SES
    ses_from_email: str | None = None
    ses_from_name: str | None = None
    ses_configuration_set: str | None = None

    # WhatsApp
    whatsapp_api_url: AnyHttpUrl | None = None
    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_business_account_id: str | None = None
    whatsapp_webhook_verify_token: SecretStr | None = None

    # Feature flags
    feature_email_enabled: bool = False
    feature_whatsapp_enabled: bool = False
    feature_background_workers_enabled: bool = False
    feature_ai_forecasting_enabled: bool = False

    @property
    def database_url(self) -> PostgresDsn:
        """Assemble the async PostgreSQL DSN from the individual connection settings."""
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=quote(self.database_user, safe=""),
            password=quote(self.database_password.get_secret_value(), safe=""),
            host=self.database_host,
            port=self.database_port,
            path=self.database_name,
        )

    @field_validator("cors_origins", "allowed_upload_mime_types", mode="before")
    @classmethod
    def parse_list_setting(cls, value: Any) -> Any:
        """Accept comma-separated environment values while preserving native list inputs."""
        if not isinstance(value, str):
            return value
        return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""
    return Settings()
