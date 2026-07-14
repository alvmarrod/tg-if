from unittest.mock import AsyncMock

from typing import Any

import pytest

from app.event_dispatcher import EventDispatcher
from domain.entities import (
    CallbackQueryEvent,
    EditedCommandEvent,
    RoutingContext,
    TelegramEvent,
)
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
        assert envelope["message_id"] == 100
        assert envelope["text"] == "Hello world"
        assert envelope["caption"] is None
        assert envelope["from_user"] is None
        assert envelope["reply_to_message_id"] is None
        assert "callback_id" not in envelope
        assert "callback_data" not in envelope

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
        # message_id is in envelope for all event types; None for non-message types
        assert envelope.get("message_id") is None

    async def test_dispatch_envelope_includes_from_user(
        self,
        dispatcher: EventDispatcher,
        private_context: RoutingContext,
        mock_publisher: AsyncMock,
    ) -> None:
        from domain.entities import MessageEvent

        event = MessageEvent(
            event_id="evt_fu_1",
            bot_id="aibot",
            chat_id=12345,
            user_id=67890,
            message_id=200,
            text="with user",
            from_user={
                "id": 67890,
                "is_bot": False,
                "first_name": "John",
                "last_name": "Doe",
                "username": "johndoe",
                "language_code": "en",
            },
        )
        dispatcher._rules["aibot"] = [
            RoutingRule(condition={"event_type": "message"}, target="topic.messages"),
        ]

        await dispatcher.dispatch(event, private_context)

        args, _ = mock_publisher.publish.await_args
        envelope = args[1]
        assert envelope["from_user"] == {
            "id": 67890,
            "is_bot": False,
            "first_name": "John",
            "last_name": "Doe",
            "username": "johndoe",
            "language_code": "en",
        }

    async def test_dispatch_command_envelope_includes_command_args(
        self,
        dispatcher: EventDispatcher,
        command_event: Any,
        private_context: RoutingContext,
        mock_publisher: AsyncMock,
    ) -> None:
        dispatcher._rules["aibot"] = [
            RoutingRule(condition={"event_type": "command"}, target="topic.commands"),
        ]

        await dispatcher.dispatch(command_event, private_context)

        args, _ = mock_publisher.publish.await_args
        envelope = args[1]
        assert envelope["text"] == "/start"
        assert envelope["command_args"] == []
        assert envelope["reply_to_message_id"] is None

    async def test_dispatch_reply_envelope_includes_reply_to_message_id(
        self,
        dispatcher: EventDispatcher,
        context_reply: RoutingContext,
        mock_publisher: AsyncMock,
    ) -> None:
        from domain.entities import MessageEvent

        event = MessageEvent(
            event_id="evt_reply_1",
            bot_id="aibot",
            chat_id=12345,
            user_id=67890,
            message_id=200,
            text="replying",
            is_reply=True,
            reply_to_message_id=42,
        )
        dispatcher._rules["aibot"] = [
            RoutingRule(condition={"event_type": "message"}, target="topic.messages"),
        ]

        await dispatcher.dispatch(event, context_reply)

        args, _ = mock_publisher.publish.await_args
        envelope = args[1]
        assert envelope["reply_to_message_id"] == 42
        assert envelope["reply_to_message"] is None
        assert envelope["routing_context"]["is_reply"] is True

    async def test_dispatch_edited_message_has_expected_structure(
        self,
        dispatcher: EventDispatcher,
        edited_message_event_text: Any,
        private_context: RoutingContext,
        mock_publisher: AsyncMock,
    ) -> None:
        dispatcher._rules["aibot"] = [
            RoutingRule(
                condition={"event_type": "edited_message"},
                target="topic.edits",
            ),
        ]

        await dispatcher.dispatch(edited_message_event_text, private_context)

        args, _ = mock_publisher.publish.await_args
        envelope = args[1]
        assert envelope["event_type"] == "edited_message"
        assert envelope["event_subtype"] == "text"
        assert envelope["bot_id"] == "aibot"
        assert envelope["chat_id"] == 12345
        assert envelope["user_id"] == 67890
        assert envelope["message_id"] == 100
        assert envelope["text"] == "Hello world (edited)"
        assert envelope["caption"] is None
        assert envelope["from_user"] is None
        assert envelope["reply_to_message_id"] is None
        assert "callback_id" not in envelope
        assert "callback_data" not in envelope

    async def test_dispatch_edited_command_includes_command_args(
        self,
        dispatcher: EventDispatcher,
        edited_command_event: EditedCommandEvent,
        private_context: RoutingContext,
        mock_publisher: AsyncMock,
    ) -> None:
        dispatcher._rules["aibot"] = [
            RoutingRule(
                condition={"event_type": "edited_message"},
                target="topic.edits",
            ),
        ]

        await dispatcher.dispatch(edited_command_event, private_context)

        args, _ = mock_publisher.publish.await_args
        envelope = args[1]
        assert envelope["event_type"] == "edited_message"
        assert envelope["text"] == "/start help"
        assert envelope["command_args"] == ["help"]
        assert envelope["reply_to_message_id"] is None
