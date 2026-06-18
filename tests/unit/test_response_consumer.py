from typing import Any
from unittest.mock import MagicMock, AsyncMock

import pytest
from pyrogram.errors import UserIsBlocked, FloodWait, MessageNotModified

from app.response_consumer import ResponseConsumer


class MockClient:
    def __init__(self, bot_id: str) -> None:
        self.bot_id = bot_id
        self.send_text = AsyncMock()
        self.send_photo = AsyncMock()
        self.send_document = AsyncMock()
        self.send_video = AsyncMock()
        self.send_audio = AsyncMock()
        self.send_media_group = AsyncMock()
        self.edit_message_text = AsyncMock()
        self.answer_callback_query = AsyncMock()


@pytest.fixture
def mock_clients() -> dict[str, Any]:
    client = MockClient("aibot")
    return {"aibot": client}


@pytest.fixture
def mock_manager() -> MagicMock:
    m = MagicMock()
    conn = MagicMock()
    conn.is_closed = False
    channel = AsyncMock()
    exchange = MagicMock()
    exchange.publish = AsyncMock()
    channel.default_exchange = exchange
    conn.channel = AsyncMock(return_value=channel)
    m.connection = conn
    return m


@pytest.fixture
def consumer(mock_clients: dict[str, Any], mock_manager: MagicMock) -> ResponseConsumer:
    return ResponseConsumer(mock_clients, mock_manager)


class TestResponseConsumer:
    async def test_handle_text_response(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
        sample_outgoing_response: dict[str, Any],
    ) -> None:
        await consumer.handle(sample_outgoing_response)

        mock_clients["aibot"].send_text.assert_awaited_once_with(
            chat_id=12345, text="Hello!", parse_mode="Markdown"
        )

    async def test_handle_photo_response(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
    ) -> None:
        body = {
            "response_id": "resp_2",
            "correlation_id": "evt_2",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "photo",
            "payload": {
                "photo": "file_id_123",
                "caption": "A photo",
                "parse_mode": "HTML",
            },
        }

        await consumer.handle(body)

        mock_clients["aibot"].send_photo.assert_awaited_once_with(
            chat_id=12345, photo="file_id_123", caption="A photo", parse_mode="HTML"
        )

    async def test_handle_media_group_response(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
    ) -> None:
        media_items = [
            {"type": "photo", "media": "file_1", "caption": "first"},
            {"type": "video", "media": "file_2"},
        ]
        body = {
            "response_id": "resp_3",
            "correlation_id": "evt_3",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "media_group",
            "payload": {"media": media_items},
        }

        await consumer.handle(body)

        mock_clients["aibot"].send_media_group.assert_awaited_once_with(
            chat_id=12345, media=media_items
        )

    async def test_handle_edit_message_text_response(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
    ) -> None:
        body = {
            "response_id": "resp_edit_1",
            "correlation_id": "evt_edit_1",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "edit_message_text",
            "payload": {"message_id": 42, "text": "Updated!"},
        }

        await consumer.handle(body)

        mock_clients["aibot"].edit_message_text.assert_awaited_once_with(
            chat_id=12345, message_id=42, text="Updated!"
        )

    async def test_handle_answer_callback_query_response(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
    ) -> None:
        body = {
            "response_id": "resp_acq_1",
            "correlation_id": "evt_acq_1",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "answer_callback_query",
            "payload": {"callback_query_id": "cq_99", "text": "Done!"},
        }

        await consumer.handle(body)

        # Must NOT pass chat_id — answer_callback_query uses callback_query_id
        mock_clients["aibot"].answer_callback_query.assert_awaited_once_with(
            callback_query_id="cq_99", text="Done!"
        )

    async def test_handle_unknown_bot_logs_error(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
    ) -> None:
        body = {
            "response_id": "resp_4",
            "correlation_id": "evt_4",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "unknown_bot",
            "chat_id": 12345,
            "response_type": "text",
            "payload": {"text": "hi"},
        }

        await consumer.handle(body)

        mock_clients["aibot"].send_text.assert_not_awaited()

    async def test_handle_unknown_response_type_logs_error(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
    ) -> None:
        body = {
            "response_id": "resp_5",
            "correlation_id": "evt_5",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "unsupported_type",
            "payload": {"data": "whatever"},
        }

        await consumer.handle(body)

        for method_name in (
            "send_text",
            "send_photo",
            "send_document",
            "send_video",
            "send_audio",
            "send_media_group",
            "edit_message_text",
            "answer_callback_query",
        ):
            getattr(mock_clients["aibot"], method_name).assert_not_awaited()

    async def test_handle_raises_on_send_failure(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
        sample_outgoing_response: dict[str, Any],
    ) -> None:
        mock_clients["aibot"].send_text.side_effect = ConnectionError(
            "telegram unavailable"
        )

        with pytest.raises(ConnectionError, match="telegram unavailable"):
            await consumer.handle(sample_outgoing_response)

    async def test_terminal_error_with_reply_to_publishes_result(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
        mock_manager: MagicMock,
    ) -> None:
        mock_clients["aibot"].send_text.side_effect = UserIsBlocked()
        body = {
            "response_id": "resp_term_1",
            "correlation_id": "evt_term_1",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "text",
            "payload": {"text": "hi"},
            "reply_to": "amq.gen-reply",
        }

        await consumer.handle(body)  # Should NOT raise

        publish = mock_manager.connection.channel.return_value.default_exchange.publish
        publish.assert_awaited_once()
        pos_args, kwargs = publish.await_args
        assert b'"failed"' in pos_args[0].body
        assert b'"USER_IS_BLOCKED"' in pos_args[0].body
        assert kwargs["routing_key"] == "amq.gen-reply"

    async def test_terminal_error_without_reply_to_skips_publish(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
        mock_manager: MagicMock,
    ) -> None:
        mock_clients["aibot"].send_text.side_effect = UserIsBlocked()
        body = {
            "response_id": "resp_term_2",
            "correlation_id": "evt_term_2",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "text",
            "payload": {"text": "hi"},
        }

        await consumer.handle(body)  # Should NOT raise

        publish = mock_manager.connection.channel.return_value.default_exchange.publish
        publish.assert_not_awaited()

    async def test_transient_error_raises_for_retry(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
        sample_outgoing_response: dict[str, Any],
    ) -> None:
        mock_clients["aibot"].send_text.side_effect = FloodWait()

        with pytest.raises(FloodWait):
            await consumer.handle(sample_outgoing_response)

    async def test_delivered_result_published_when_reply_to_set(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
        mock_manager: MagicMock,
    ) -> None:
        body = {
            "response_id": "resp_del_1",
            "correlation_id": "evt_del_1",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "text",
            "payload": {"text": "ok"},
            "reply_to": "amq.gen-reply",
        }

        await consumer.handle(body)

        publish = mock_manager.connection.channel.return_value.default_exchange.publish
        publish.assert_awaited_once()
        pos_args, kwargs = publish.await_args
        assert b'"delivered"' in pos_args[0].body
        assert kwargs["routing_key"] == "amq.gen-reply"

    async def test_unknown_bot_with_reply_to_publishes_failure(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
        mock_manager: MagicMock,
    ) -> None:
        body = {
            "response_id": "resp_unk_1",
            "correlation_id": "evt_unk_1",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "nonexistent",
            "chat_id": 12345,
            "response_type": "text",
            "payload": {"text": "hi"},
            "reply_to": "amq.gen-reply",
        }

        await consumer.handle(body)

        publish = mock_manager.connection.channel.return_value.default_exchange.publish
        publish.assert_awaited_once()
        pos_args, kwargs = publish.await_args
        assert b'"failed"' in pos_args[0].body
        assert b'"UNKNOWN_BOT"' in pos_args[0].body
        assert kwargs["routing_key"] == "amq.gen-reply"

    async def test_handle_not_connected_skips_publish(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
        mock_manager: MagicMock,
    ) -> None:
        mock_manager.connection = None
        mock_clients["aibot"].send_text.side_effect = UserIsBlocked()
        body = {
            "response_id": "resp_nc_1",
            "correlation_id": "evt_nc_1",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "text",
            "payload": {"text": "hi"},
            "reply_to": "amq.gen-reply",
        }

        await consumer.handle(body)  # Should NOT raise

    async def test_message_not_modified_is_terminal(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
        mock_manager: MagicMock,
    ) -> None:

        mock_clients["aibot"].edit_message_text.side_effect = MessageNotModified()
        body = {
            "response_id": "resp_mnm_1",
            "correlation_id": "evt_mnm_1",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "edit_message_text",
            "payload": {"message_id": 42, "text": "same"},
        }

        await consumer.handle(body)  # Should NOT raise (terminal, not retried)
