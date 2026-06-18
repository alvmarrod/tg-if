from unittest.mock import AsyncMock

from typing import Any

import pytest

from app.event_dispatcher import EventDispatcher
from domain.entities import CallbackQueryEvent, RoutingContext, TelegramEvent
from domain.rules import RoutingRule
from infrastructure.broker import Publisher


@pytest.fixture
def mock_publisher() -> AsyncMock:
    pub = AsyncMock(spec=Publisher)
    pub.publish = AsyncMock()
    return pub


@pytest.fixture
def bot_configs() -> list[dict[str, Any]]:
    return [
        {
            "name": "aibot",
            "api_id": 12345,
            "api_hash": "hash_a",
            "session_file": "sessions/aibot.session",
            "routing_rules": [
                RoutingRule(
                    condition={"event_type": "message"}, target="topic.messages"
                ),
                RoutingRule(
                    condition={"event_type": "callback_query"},
                    target="topic.callbacks",
                ),
            ],
        },
    ]


@pytest.fixture
def dispatcher(
    bot_configs: list[dict[str, Any]], mock_publisher: AsyncMock
) -> EventDispatcher:
    from infrastructure.config import BotConfig

    configs = [BotConfig.model_validate(c) for c in bot_configs]
    return EventDispatcher(configs, mock_publisher)


class TestEventDispatcher:
    async def test_dispatch_matched_routes_to_publisher(
        self,
        dispatcher: EventDispatcher,
        message_event_text: TelegramEvent,
        private_context: RoutingContext,
        mock_publisher: AsyncMock,
    ) -> None:
        decision = await dispatcher.dispatch(message_event_text, private_context)

        assert decision.matched is True
        assert decision.target == "topic.messages"
        mock_publisher.publish.assert_awaited_once()
        args, _ = mock_publisher.publish.await_args
        assert args[0] == "topic.messages"

    async def test_dispatch_envelope_has_expected_structure(
        self,
        dispatcher: EventDispatcher,
        message_event_text: TelegramEvent,
        private_context: RoutingContext,
        mock_publisher: AsyncMock,
    ) -> None:
        await dispatcher.dispatch(message_event_text, private_context)

        args, _ = mock_publisher.publish.await_args
        envelope = args[1]
        assert "event_id" in envelope
        assert "timestamp" in envelope
        assert "bot_id" in envelope
        assert envelope["bot_id"] == "aibot"
        assert "event_type" in envelope
        assert envelope["event_type"] == "message"
        assert "event_subtype" in envelope
        assert "chat_id" in envelope
        assert envelope["chat_id"] == 12345
        assert "user_id" in envelope
        assert envelope["user_id"] == 67890
        assert "routing_context" in envelope
        assert "payload" in envelope
        assert "callback_id" not in envelope
        assert "callback_data" not in envelope
        assert "message_id" not in envelope

    async def test_dispatch_no_match_does_not_publish(
        self,
        dispatcher: EventDispatcher,
        message_event_text: TelegramEvent,
        private_context: RoutingContext,
        mock_publisher: AsyncMock,
    ) -> None:
        dispatcher._rules["aibot"] = [
            RoutingRule(
                condition={"event_type": "callback_query"},
                target="topic.callbacks",
            ),
        ]

        decision = await dispatcher.dispatch(message_event_text, private_context)

        assert decision.matched is False
        mock_publisher.publish.assert_not_awaited()

    async def test_dispatch_unknown_bot(
        self,
        dispatcher: EventDispatcher,
        message_event_text: TelegramEvent,
        private_context: RoutingContext,
        mock_publisher: AsyncMock,
    ) -> None:
        message_event_text.bot_id = "nonexistent"

        decision = await dispatcher.dispatch(message_event_text, private_context)

        assert decision.matched is False
        mock_publisher.publish.assert_not_awaited()

    async def test_dispatch_callback_query_includes_callback_fields(
        self,
        dispatcher: EventDispatcher,
        callback_event: CallbackQueryEvent,
        private_context: RoutingContext,
        mock_publisher: AsyncMock,
    ) -> None:
        dispatcher._rules["aibot"] = [
            RoutingRule(
                condition={"event_type": "callback_query"},
                target="topic.callbacks",
            ),
        ]

        decision = await dispatcher.dispatch(callback_event, private_context)

        assert decision.matched is True
        assert decision.target == "topic.callbacks"
        mock_publisher.publish.assert_awaited_once()
        args, _ = mock_publisher.publish.await_args
        envelope = args[1]
        assert envelope["event_type"] == "callback_query"
        assert envelope["callback_id"] == "cb_1"
        assert envelope["callback_data"] == "option_1"
        assert envelope["message_id"] == 100
        assert envelope["chat_id"] == 12345

    async def test_dispatch_callback_query_no_message_id_omits_field(
        self,
        dispatcher: EventDispatcher,
        callback_event: CallbackQueryEvent,
        private_context: RoutingContext,
        mock_publisher: AsyncMock,
    ) -> None:
        callback_event.message_id = None
        dispatcher._rules["aibot"] = [
            RoutingRule(
                condition={"event_type": "callback_query"},
                target="topic.callbacks",
            ),
        ]

        decision = await dispatcher.dispatch(callback_event, private_context)

        assert decision.matched is True
        args, _ = mock_publisher.publish.await_args
        envelope = args[1]
        assert envelope["callback_id"] == "cb_1"
        assert envelope["callback_data"] == "option_1"
        assert "message_id" not in envelope
