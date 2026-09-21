"""SES transport unit tests."""

from typing import Any

import pytest
from botocore.exceptions import ClientError

from app.core.exceptions import IntegrationError
from app.integrations.email.client import SesEmailTransport
from app.integrations.email.schemas import EmailMessage


class FakeSesClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_email(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(kwargs)
        return {"MessageId": "msg-123"}


class BoomSesClient(FakeSesClient):
    def send_email(self, **kwargs: Any) -> dict[str, str]:
        raise ClientError({"Error": {"Code": "500", "Message": "fail"}}, "SendEmail")


@pytest.mark.asyncio
async def test_ses_send_plain_and_html() -> None:
    client = FakeSesClient()
    transport = SesEmailTransport(
        client,
        from_email="noreply@example.com",
        from_name="Plumbit",
        configuration_set=None,
    )
    message_id = await transport.send(
        EmailMessage(
            to="user@example.com",
            subject="Hello",
            text_body="Plain",
            html_body="<p>Plain</p>",
        )
    )
    assert message_id == "msg-123"
    assert len(client.calls) == 1
    body = client.calls[0]["Message"]["Body"]
    assert "Html" in body
    assert "Text" in body


@pytest.mark.asyncio
async def test_ses_send_failure_raises_integration_error() -> None:
    transport = SesEmailTransport(
        BoomSesClient(),
        from_email="noreply@example.com",
        from_name=None,
        configuration_set=None,
    )
    with pytest.raises(IntegrationError, match="Failed to send email"):
        await transport.send(
            EmailMessage(to="user@example.com", subject="Hello", text_body="Plain")
        )
