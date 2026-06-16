from __future__ import annotations

from unittest.mock import AsyncMock

from app.admin_notifier import AdminNotifier, _format_signal
from domain.schemas import AdminSignalType


class MockClient:
    def __init__(self) -> None:
        self.bot_id = "__admin__"
        self.send_text = AsyncMock()
        self.start = AsyncMock()
        self.stop = AsyncMock()
        self.health = AsyncMock(return_value=True)


class TestAdminNotifier:
    async def test_notify_response_failed_sends_text(self) -> None:
        client = MockClient()
        config = AsyncMock()
        config.user_id = 999
        notifier = AdminNotifier(config, client=client)  # type: ignore[arg-type]

        body = {
            "bot_id": "aibot",
            "response_type": "text",
            "chat_id": 12345,
            "response_id": "resp_abc",
        }
        exc = ValueError("telegram unavailable")

        await notifier.notify(AdminSignalType.RESPONSE_FAILED, body=body, exc=exc)

        client.send_text.assert_awaited_once()
        _args = client.send_text.await_args
        assert _args is not None
        assert _args[0][0] == 999
        assert "⚠️ Response Failed" in _args[0][1]
        assert "aibot" in _args[0][1]
        assert "telegram unavailable" in _args[0][1]

    async def test_notify_component_connected(self) -> None:
        client = MockClient()
        config = AsyncMock()
        config.user_id = 999
        notifier = AdminNotifier(config, client=client)  # type: ignore[arg-type]

        await notifier.notify(AdminSignalType.COMPONENT_CONNECTED, component="broker")

        client.send_text.assert_awaited_once()
        _args = client.send_text.await_args
        assert _args is not None
        assert "✅" in _args[0][1]
        assert "broker" in _args[0][1]

    async def test_notify_component_disconnected(self) -> None:
        client = MockClient()
        config = AsyncMock()
        config.user_id = 999
        notifier = AdminNotifier(config, client=client)  # type: ignore[arg-type]

        await notifier.notify(AdminSignalType.COMPONENT_DISCONNECTED, component="aibot")

        client.send_text.assert_awaited_once()
        _args = client.send_text.await_args
        assert _args is not None
        assert "❌" in _args[0][1]
        assert "aibot" in _args[0][1]

    async def test_notify_send_failure_does_not_crash(self) -> None:
        client = MockClient()
        client.send_text.side_effect = ConnectionError("network down")
        config = AsyncMock()
        config.user_id = 999
        notifier = AdminNotifier(config, client=client)  # type: ignore[arg-type]

        await notifier.notify(
            AdminSignalType.RESPONSE_FAILED,
            body={},
            exc=ValueError("fail"),
        )

    async def test_unknown_signal_type(self) -> None:
        text = _format_signal("unsupported", key="val")  # type: ignore[arg-type]
        assert "Unknown signal" in text

    async def test_health_proxy(self) -> None:
        client = MockClient()
        config = AsyncMock()
        notifier = AdminNotifier(config, client=client)  # type: ignore[arg-type]

        ok = await notifier.health()

        assert ok is True
        client.health.assert_awaited_once()

    async def test_start_stop(self) -> None:
        client = MockClient()
        config = AsyncMock()
        notifier = AdminNotifier(config, client=client)  # type: ignore[arg-type]

        await notifier.start()
        client.start.assert_awaited_once()

        await notifier.stop()
        client.stop.assert_awaited_once()
