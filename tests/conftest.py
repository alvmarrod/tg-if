from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from domain.entities import (
    CallbackQueryEvent,
    ChatType,
    CommandEvent,
    MessageEvent,
    RoutingContext,
)


@pytest.fixture
def message_event_text() -> MessageEvent:
    return MessageEvent(
        event_id=str(uuid4()),
        timestamp=datetime.now(timezone.utc),
        bot_id="aibot",
        chat_id=12345,
        user_id=67890,
        message_id=100,
        text="Hello world",
    )


@pytest.fixture
def message_event_photo() -> MessageEvent:
    return MessageEvent(
        event_id=str(uuid4()),
        timestamp=datetime.now(timezone.utc),
        bot_id="aibot",
        chat_id=12345,
        user_id=67890,
        message_id=101,
        text=None,
        caption="A photo",
        has_media=True,
        media_type="photo",
    )


@pytest.fixture
def command_event() -> CommandEvent:
    return CommandEvent(
        event_id=str(uuid4()),
        timestamp=datetime.now(timezone.utc),
        bot_id="aibot",
        chat_id=12345,
        user_id=67890,
        message_id=102,
        command="start",
        command_args=[],
        text="/start",
    )


@pytest.fixture
def callback_event() -> CallbackQueryEvent:
    return CallbackQueryEvent(
        event_id=str(uuid4()),
        timestamp=datetime.now(timezone.utc),
        bot_id="aibot",
        chat_id=12345,
        user_id=67890,
        callback_id="cb_1",
        callback_data="option_1",
        message_id=100,
    )


@pytest.fixture
def private_context() -> RoutingContext:
    return RoutingContext(chat_type=ChatType.PRIVATE)


@pytest.fixture
def group_context() -> RoutingContext:
    return RoutingContext(chat_type=ChatType.GROUP)


@pytest.fixture
def media_context() -> RoutingContext:
    return RoutingContext(
        chat_type=ChatType.PRIVATE,
        has_media=True,
        media_type="photo",
    )


@pytest.fixture
def message_event_reply() -> MessageEvent:
    return MessageEvent(
        event_id=str(uuid4()),
        timestamp=datetime.now(timezone.utc),
        bot_id="aibot",
        chat_id=12345,
        user_id=67890,
        message_id=103,
        text="A reply",
        is_reply=True,
        reply_to_message_id=42,
    )


@pytest.fixture
def message_event_forward() -> MessageEvent:
    return MessageEvent(
        event_id=str(uuid4()),
        timestamp=datetime.now(timezone.utc),
        bot_id="aibot",
        chat_id=12345,
        user_id=67890,
        message_id=104,
        text="A forwarded message",
        is_forward=True,
    )


@pytest.fixture
def context_reply() -> RoutingContext:
    return RoutingContext(chat_type=ChatType.PRIVATE, is_reply=True)


@pytest.fixture
def context_forward() -> RoutingContext:
    return RoutingContext(chat_type=ChatType.PRIVATE, is_forward=True)


@pytest.fixture
def sample_outgoing_response() -> dict[str, Any]:
    return {
        "response_id": "resp_1",
        "correlation_id": "evt_1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bot_id": "aibot",
        "chat_id": 12345,
        "response_type": "text",
        "payload": {"text": "Hello!", "parse_mode": "Markdown"},
    }
