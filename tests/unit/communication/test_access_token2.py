"""AccessToken2 structure tests."""

from app.integrations.agora.rtc_token_builder2 import Role_Publisher, RtcTokenBuilder

APP_ID = "01234567890123456789012345678901"
CERT = "01234567890123456789012345678901"


def test_rtc_token_has_007_prefix() -> None:
    token = RtcTokenBuilder.build_token_with_uid(
        APP_ID, CERT, "test-channel", 1, Role_Publisher, 600, 600
    )
    assert token[:3] == "007"
