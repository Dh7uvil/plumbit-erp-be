"""Centralized, environment-backed application configuration."""

from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import AnyHttpUrl, Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Validated settings loaded from environment variables and an optional local `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
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
    database_url: PostgresDsn
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
    cors_allow_credentials: bool = True
    cors_allow_methods: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    )
    cors_allow_headers: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["Authorization", "Content-Type", "X-Request-ID"]
    )

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
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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

    @field_validator(
        "cors_origins",
        "cors_allow_methods",
        "cors_allow_headers",
        "allowed_upload_mime_types",
        mode="before",
    )
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
