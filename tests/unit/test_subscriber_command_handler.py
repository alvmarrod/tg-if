from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bot_command_registry import BotCommandRegistry
from app.subscriber_command_handler import SubscriberCommandHandler


@pytest.fixture
def registry() -> BotCommandRegistry:
    return BotCommandRegistry()


@pytest.fixture
def mock_client() -> Any:
    client = MagicMock()
    client.bot_id = "aibot"
    client.set_bot_commands = AsyncMock()
    return client


@pytest.fixture
def clients(mock_client: Any) -> dict[str, Any]:
    return {"aibot": mock_client}


@pytest.fixture
def mock_manager() -> Any:
    m = MagicMock()
    m.connection = MagicMock()
    return m


@pytest.fixture
def handler(
    registry: BotCommandRegistry,
    clients: dict[str, Any],
    mock_manager: Any,
) -> SubscriberCommandHandler:
    return SubscriberCommandHandler(registry, clients, mock_manager)


class TestSubscriberCommandHandler:
    async def test_register_calls_set_bot_commands(
        self,
        handler: SubscriberCommandHandler,
        mock_client: Any,
    ) -> None:
        body = {
            "action": "register",
            "bot_id": "aibot",
            "subscriber_id": "svc_1",
            "commands": [{"command": "start", "description": "Start"}],
        }
        await handler.handle(body)
        mock_client.set_bot_commands.assert_awaited_once_with([("start", "Start")])

    async def test_register_without_reply_to(
        self,
        handler: SubscriberCommandHandler,
        mock_client: Any,
    ) -> None:
        body = {
            "action": "register",
            "bot_id": "aibot",
            "subscriber_id": "svc_1",
            "commands": [{"command": "start", "description": "Start"}],
        }
        await handler.handle(body)
        mock_client.set_bot_commands.assert_awaited_once()

    async def test_deregister_calls_set_bot_commands(
        self,
        handler: SubscriberCommandHandler,
        mock_client: Any,
        registry: BotCommandRegistry,
    ) -> None:
        registry.register(
            "aibot",
            "svc_1",
            [{"command": "start", "description": "Start"}],
        )
        mock_client.set_bot_commands.reset_mock()

        body = {
            "action": "deregister",
            "bot_id": "aibot",
            "subscriber_id": "svc_1",
            "commands": [],
        }
        await handler.handle(body)
        mock_client.set_bot_commands.assert_awaited_once_with([])

    async def test_unknown_bot_logs_error(
        self,
        handler: SubscriberCommandHandler,
        mock_client: Any,
    ) -> None:
        body = {
            "action": "register",
            "bot_id": "unknown_bot",
            "subscriber_id": "svc_1",
            "commands": [{"command": "start", "description": "Start"}],
        }
        await handler.handle(body)
        mock_client.set_bot_commands.assert_not_awaited()

    async def test_conflict_does_not_call_set_bot_commands(
        self,
        handler: SubscriberCommandHandler,
        mock_client: Any,
        registry: BotCommandRegistry,
    ) -> None:
        registry.register(
            "aibot",
            "svc_1",
            [{"command": "start", "description": "Start"}],
        )
        mock_client.set_bot_commands.reset_mock()

        body = {
            "action": "register",
            "bot_id": "aibot",
            "subscriber_id": "svc_2",
            "commands": [{"command": "start", "description": "Also Start"}],
        }
        await handler.handle(body)
        mock_client.set_bot_commands.assert_not_awaited()

    async def test_invalid_envelope_logs_error(
        self,
        handler: SubscriberCommandHandler,
        mock_client: Any,
    ) -> None:
        body: dict[str, Any] = {"bad": "data"}
        await handler.handle(body)
        mock_client.set_bot_commands.assert_not_awaited()
