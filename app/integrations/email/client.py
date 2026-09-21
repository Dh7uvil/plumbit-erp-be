"""Amazon SES email delivery."""

from __future__ import annotations

import asyncio
import logging
from email.utils import formataddr
from functools import lru_cache
from typing import Any, Protocol, cast

from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from app.core.config import Settings, get_settings
from app.core.exceptions import IntegrationError
from app.integrations.email.schemas import EmailMessage

logger = logging.getLogger(__name__)


class SesClientProtocol(Protocol):
    def send_email(self, **kwargs: Any) -> Any: ...


class SesEmailTransport:
    """Send plain and HTML email through SES."""

    def __init__(
        self,
        client: SesClientProtocol,
        *,
        from_email: str,
        from_name: str | None,
        configuration_set: str | None,
    ) -> None:
        self._client = client
        self._from_email = from_email
        self._from_name = from_name
        self._configuration_set = configuration_set

    @classmethod
    def from_settings(cls, settings: Settings) -> SesEmailTransport:
        if not settings.ses_from_email:
            raise IntegrationError("Email is not configured (SES_FROM_EMAIL is missing)")
        return cls(
            _build_boto3_ses_client(settings),
            from_email=settings.ses_from_email,
            from_name=settings.ses_from_name,
            configuration_set=settings.ses_configuration_set,
        )

    async def send(self, message: EmailMessage) -> str:
        """Deliver one message. Returns the SES MessageId."""

        return await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: EmailMessage) -> str:
        source = (
            formataddr((self._from_name, self._from_email))
            if self._from_name
            else self._from_email
        )
        body: dict[str, Any] = {"Text": {"Data": message.text_body, "Charset": "UTF-8"}}
        if message.html_body:
            body["Html"] = {"Data": message.html_body, "Charset": "UTF-8"}
        kwargs: dict[str, Any] = {
            "Source": source,
            "Destination": {"ToAddresses": [message.to]},
            "Message": {
                "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                "Body": body,
            },
        }
        if message.reply_to:
            kwargs["ReplyToAddresses"] = [message.reply_to]
        if self._configuration_set:
            kwargs["ConfigurationSetName"] = self._configuration_set
        try:
            response = self._client.send_email(**kwargs)
        except (BotoCoreError, ClientError) as exc:
            raise IntegrationError("Failed to send email") from exc
        message_id = response.get("MessageId")
        if not isinstance(message_id, str):
            raise IntegrationError("SES did not return a MessageId")
        logger.info("email_sent", extra={"message_id": message_id, "to": message.to})
        return message_id


def _build_boto3_ses_client(settings: Settings) -> SesClientProtocol:
    import boto3  # type: ignore[import-untyped]

    kwargs: dict[str, Any] = {"service_name": "ses"}
    if settings.aws_region:
        kwargs["region_name"] = settings.aws_region
    if settings.aws_access_key_id is not None and settings.aws_secret_access_key is not None:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id.get_secret_value()
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key.get_secret_value()
    return cast(SesClientProtocol, boto3.client(**kwargs))


@lru_cache
def get_email_transport() -> SesEmailTransport:
    return SesEmailTransport.from_settings(get_settings())


def get_optional_email_transport() -> SesEmailTransport | None:
    settings = get_settings()
    if not settings.feature_email_enabled or not settings.ses_from_email:
        return None
    return get_email_transport()
