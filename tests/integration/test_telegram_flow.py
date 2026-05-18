import pytest

pytestmark = pytest.mark.skip(
    reason="requires Telegram session files and API credentials"
)


class TestTelegramFlow:
    async def test_event_to_publish_flow(self) -> None:
        pass

    async def test_response_to_send_flow(self) -> None:
        pass
