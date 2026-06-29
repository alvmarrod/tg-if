from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pyrogram.errors import UserIsBlocked, FloodWait, MessageNotModified

from app.response_consumer import ResponseConsumer
from infrastructure.media.storage import MediaStorage
from infrastructure.sqlite import UploadRegistry
from pyrogram.errors import MessageDeleteForbidden


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
        self.delete_message = AsyncMock()


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
def mock_registry() -> MagicMock:
    m = MagicMock(spec=UploadRegistry)
    m.get_by_hash = MagicMock()
    m.touch_usage = MagicMock()
    m.update_file_id = MagicMock()
    return m


@pytest.fixture
def mock_storage() -> MagicMock:
    m = MagicMock(spec=MediaStorage)
    m.path_for = AsyncMock()
    return m


@pytest.fixture
def consumer(mock_clients: dict[str, Any], mock_manager: MagicMock) -> ResponseConsumer:
    return ResponseConsumer(mock_clients, mock_manager)


@pytest.fixture
def consumer_with_upload(
    mock_clients: dict[str, Any],
    mock_manager: MagicMock,
    mock_registry: MagicMock,
    mock_storage: MagicMock,
) -> ResponseConsumer:
    return ResponseConsumer(
        mock_clients,
        mock_manager,
        registry=mock_registry,
        upload_storage=mock_storage,
    )


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
            "delete_message",
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


class TestUploadResolution:
    async def test_resolve_upload_fast_path(
        self,
        consumer_with_upload: ResponseConsumer,
        mock_registry: MagicMock,
        mock_storage: MagicMock,
    ) -> None:
        mock_registry.get_by_hash.return_value = MagicMock(
            content_hash="abc", file_id="AgAC...", bot_id="aibot"
        )
        resolved, ch = await consumer_with_upload._resolve_upload("aibot", "upl_abc")
        assert resolved == "AgAC..."
        assert ch == "abc"
        mock_registry.touch_usage.assert_called_once_with("abc")
        mock_storage.path_for.assert_not_called()

    async def test_resolve_upload_slow_path(
        self,
        consumer_with_upload: ResponseConsumer,
        mock_registry: MagicMock,
        mock_storage: MagicMock,
    ) -> None:
        entry = MagicMock(content_hash="abc", file_id=None, bot_id="aibot")
        entry.file_id = None
        mock_registry.get_by_hash.return_value = entry
        mock_storage.path_for.return_value = Path("/data/uploads/aibot/abc.bin")

        resolved, ch = await consumer_with_upload._resolve_upload("aibot", "upl_abc")
        assert isinstance(resolved, str)
        assert resolved == str(Path("/data/uploads/aibot/abc.bin"))
        assert ch == "abc"
        mock_storage.path_for.assert_awaited_once_with("aibot", "abc")

    async def test_resolve_upload_not_found(
        self,
        consumer_with_upload: ResponseConsumer,
        mock_registry: MagicMock,
        mock_storage: MagicMock,
    ) -> None:
        mock_registry.get_by_hash.return_value = None
        mock_storage.path_for.return_value = None
        with pytest.raises(ValueError, match="upload.*abc.*not found"):
            await consumer_with_upload._resolve_upload("aibot", "upl_abc")

    async def test_resolve_no_upload_configured(
        self,
        consumer: ResponseConsumer,
    ) -> None:
        with pytest.raises(ValueError, match="upload.*not found"):
            await consumer._resolve_upload("aibot", "upl_abc")

    async def test_resolve_non_upload_value_passthrough(
        self,
        consumer_with_upload: ResponseConsumer,
        mock_registry: MagicMock,
    ) -> None:
        resolved, ch = await consumer_with_upload._resolve_upload(
            "aibot", "file_id_123"
        )
        assert resolved == "file_id_123"
        assert ch is None
        mock_registry.get_by_hash.assert_not_called()

    async def test_resolve_empty_string_passthrough(
        self,
        consumer_with_upload: ResponseConsumer,
        mock_registry: MagicMock,
    ) -> None:
        resolved, ch = await consumer_with_upload._resolve_upload("aibot", "")
        assert resolved == ""
        assert ch is None
        mock_registry.get_by_hash.assert_not_called()

    async def test_resolve_just_prefix_no_entry(
        self,
        consumer_with_upload: ResponseConsumer,
        mock_registry: MagicMock,
        mock_storage: MagicMock,
    ) -> None:
        mock_registry.get_by_hash.return_value = None
        mock_storage.path_for.return_value = None
        with pytest.raises(ValueError, match="upload.*not found"):
            await consumer_with_upload._resolve_upload("aibot", "upl_")

    async def test_update_after_send_single_file_id(
        self,
        consumer_with_upload: ResponseConsumer,
        mock_registry: MagicMock,
    ) -> None:
        mock_result = MagicMock()
        photo_attr = MagicMock()
        photo_attr.file_id = "AgAC..."
        photo_attr.file_unique_id = "QQAD..."
        mock_result.photo = photo_attr

        await consumer_with_upload._update_after_send("photo", mock_result, ["abc123"])
        mock_registry.update_file_id.assert_called_once_with(
            "abc123", "AgAC...", "QQAD..."
        )

    async def test_update_after_send_no_registry(
        self,
        consumer: ResponseConsumer,
    ) -> None:
        mock_result = MagicMock()
        await consumer._update_after_send("photo", mock_result, ["abc"])
        assert True  # no error

    async def test_update_after_send_empty_hashes(
        self,
        consumer_with_upload: ResponseConsumer,
        mock_registry: MagicMock,
    ) -> None:
        mock_result = MagicMock()
        await consumer_with_upload._update_after_send("photo", mock_result, [])
        mock_registry.update_file_id.assert_not_called()

    async def test_update_after_send_media_group(
        self,
        consumer_with_upload: ResponseConsumer,
        mock_registry: MagicMock,
    ) -> None:
        mock_results = [
            MagicMock(),
            MagicMock(),
        ]
        photo_attr = MagicMock()
        photo_attr.file_id = "AgAC1..."
        photo_attr.file_unique_id = "QQAD1..."
        mock_results[0].photo = photo_attr

        mock_results[1].photo = None
        video_attr = MagicMock()
        video_attr.file_id = "AgAC2..."
        video_attr.file_unique_id = "QQAD2..."
        mock_results[1].video = video_attr

        await consumer_with_upload._update_after_send(
            "media_group", mock_results, ["hash1", "hash2"]
        )
        assert mock_registry.update_file_id.call_count == 2
        mock_registry.update_file_id.assert_any_call("hash1", "AgAC1...", "QQAD1...")
        mock_registry.update_file_id.assert_any_call("hash2", "AgAC2...", "QQAD2...")

    async def test_handle_photo_with_upl_resolves_and_publishes(
        self,
        consumer_with_upload: ResponseConsumer,
        mock_clients: dict[str, Any],
        mock_registry: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        mock_registry.get_by_hash.return_value = MagicMock(
            content_hash="abc", file_id="AgAC...", bot_id="aibot"
        )
        body = {
            "response_id": "resp_upl_1",
            "correlation_id": "evt_upl_1",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "photo",
            "payload": {"photo": "upl_abc", "caption": "upl test"},
        }

        await consumer_with_upload.handle(body)

        mock_registry.get_by_hash.assert_called_once_with("abc")
        mock_clients["aibot"].send_photo.assert_awaited_once_with(
            chat_id=12345, photo="AgAC...", caption="upl test"
        )

    async def test_handle_media_group_with_upl_resolves(
        self,
        consumer_with_upload: ResponseConsumer,
        mock_clients: dict[str, Any],
        mock_registry: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        mock_registry.get_by_hash.return_value = MagicMock(
            content_hash="def", file_id="AgAC2...", bot_id="aibot"
        )
        body = {
            "response_id": "resp_upl_mg",
            "correlation_id": "evt_upl_mg",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "media_group",
            "payload": {
                "media": [
                    {"type": "photo", "media": "upl_def", "caption": "upl mg"},
                ]
            },
        }

        await consumer_with_upload.handle(body)

        mock_clients["aibot"].send_media_group.assert_awaited_once()
        media_arg = mock_clients["aibot"].send_media_group.await_args.kwargs["media"]
        assert media_arg[0]["media"] == "AgAC2..."

    async def test_handle_with_upl_mixed_keeps_non_upl_intact(
        self,
        consumer_with_upload: ResponseConsumer,
        mock_clients: dict[str, Any],
        mock_registry: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        mock_registry.get_by_hash.return_value = MagicMock(
            content_hash="abc", file_id="AgAC...", bot_id="aibot"
        )
        body = {
            "response_id": "resp_upl_mix",
            "correlation_id": "evt_upl_mix",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "document",
            "payload": {
                "document": "upl_abc",
                "thumb": "file_id_thumb",
                "caption": "mixed",
            },
        }

        await consumer_with_upload.handle(body)

        kwargs = mock_clients["aibot"].send_document.await_args.kwargs
        assert kwargs["document"] == "AgAC..."
        assert kwargs["thumb"] == "file_id_thumb"
        assert kwargs["caption"] == "mixed"


class TestDeleteMessage:
    async def test_handle_delete_message_single(
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
            "response_type": "delete_message",
            "payload": {"message_ids": [42]},
        }

        await consumer.handle(body)

        mock_clients["aibot"].delete_message.assert_awaited_once_with(
            chat_id=12345, message_ids=[42]
        )

    async def test_handle_delete_message_multiple(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
        mock_manager: MagicMock,
    ) -> None:
        body = {
            "response_id": "resp_del_2",
            "correlation_id": "evt_del_2",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "delete_message",
            "payload": {"message_ids": [1, 2, 3]},
        }

        await consumer.handle(body)

        mock_clients["aibot"].delete_message.assert_awaited_once_with(
            chat_id=12345, message_ids=[1, 2, 3]
        )

    async def test_handle_delete_message_terminal_error(
        self,
        consumer: ResponseConsumer,
        mock_clients: dict[str, Any],
        mock_manager: MagicMock,
    ) -> None:
        mock_clients["aibot"].delete_message.side_effect = MessageDeleteForbidden()
        body = {
            "response_id": "resp_del_3",
            "correlation_id": "evt_del_3",
            "timestamp": "2025-01-01T00:00:00",
            "bot_id": "aibot",
            "chat_id": 12345,
            "response_type": "delete_message",
            "payload": {"message_ids": [42]},
            "reply_to": "amq.gen-reply",
        }

        await consumer.handle(body)  # Should NOT raise

        publish = mock_manager.connection.channel.return_value.default_exchange.publish
        publish.assert_awaited_once()
        pos_args, kwargs = publish.await_args
        assert b'"failed"' in pos_args[0].body
        assert b'"MESSAGE_DELETE_FORBIDDEN"' in pos_args[0].body
        assert kwargs["routing_key"] == "amq.gen-reply"
