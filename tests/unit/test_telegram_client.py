from __future__ import annotations

import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.config import BotConfig
from infrastructure.telegram.client import TelegramClient, _parse_mode


def _async_gen(items: list[Any]) -> AsyncMock:
    """Create an async generator mock that yields the given items."""
    gen = AsyncMock()
    gen.__aiter__.return_value = iter(items)
    return gen


@pytest.fixture
def raw_client() -> MagicMock:
    client = MagicMock()
    client.get_chat_history = MagicMock()
    client.download_media = AsyncMock()
    client.send_message = AsyncMock()
    client.send_photo = AsyncMock()
    client.send_document = AsyncMock()
    client.send_video = AsyncMock()
    client.send_audio = AsyncMock()
    client.edit_message_text = AsyncMock()
    client.edit_message_reply_markup = AsyncMock()
    client.answer_callback_query = AsyncMock()
    client.send_media_group = AsyncMock()
    client.delete_messages = AsyncMock()
    client.is_connected = True
    return client


@pytest.fixture
def bot_config() -> BotConfig:
    return BotConfig(
        name="testbot",
        api_id=12345,
        api_hash="abc123",
        bot_token="12345:abcdeftoken",
        session_file="sessions/test.session",
    )


@pytest.fixture
def user_config() -> BotConfig:
    return BotConfig(
        name="userbot",
        api_id=12345,
        api_hash="abc123",
        session_file="sessions/user.session",
    )


@pytest.fixture
def telegram_client(raw_client: MagicMock, bot_config: BotConfig) -> TelegramClient:
    tc = TelegramClient(config=bot_config)
    tc._client = raw_client
    return tc


@pytest.fixture
def user_client(raw_client: MagicMock, user_config: BotConfig) -> TelegramClient:
    tc = TelegramClient(config=user_config)
    tc._client = raw_client
    return tc


def _make_chat(chat_id: int, title: str, chat_type_str: str) -> MagicMock:
    chat = MagicMock()
    chat.id = chat_id
    chat.title = title
    chat.first_name = None
    chat.last_name = None
    chat.type = f"ChatType.{chat_type_str.upper()}"
    chat.member_count = 42
    chat.permissions = MagicMock()
    chat.permissions.can_send_messages = True
    return chat


class TestTelegramClientExport:
    async def test_known_chats_returns_registered(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        chat_a = _make_chat(-100123, "Group A", "supergroup")
        chat_b = _make_chat(456, "User B", "private")
        telegram_client._register_chat(chat_a)
        telegram_client._register_chat(chat_b)

        result = telegram_client.known_chats
        assert len(result) == 2
        assert result[0]["chat_id"] == -100123
        assert result[0]["title"] == "Group A"
        assert result[0]["type"] == "supergroup"
        assert result[0]["can_read"] is True
        assert result[1]["chat_id"] == 456
        assert result[1]["title"] == "User B"
        assert result[1]["can_read"] is True

    async def test_known_chats_empty_by_default(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        assert telegram_client.known_chats == []

    async def test_known_chats_updates_existing(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        chat = _make_chat(100, "Old Name", "private")
        telegram_client._register_chat(chat)
        chat.title = "New Name"
        telegram_client._register_chat(chat)
        assert len(telegram_client.known_chats) == 1
        assert telegram_client.known_chats[0]["title"] == "New Name"

    async def test_get_chat_history_returns_messages(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        msg1 = MagicMock()
        msg1.message_id = 1
        msg2 = MagicMock()
        msg2.message_id = 2
        raw_client.get_chat_history.return_value = _async_gen([msg1, msg2])
        result = await telegram_client.get_chat_history(chat_id=-100123, limit=10)
        assert len(result) == 2
        assert result[0].message_id == 1

    async def test_get_chat_history_with_offset(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.get_chat_history.return_value = _async_gen([])
        await telegram_client.get_chat_history(
            chat_id=-100456, offset_id=500, offset_date="2026-01-01"
        )

    async def test_download_media_returns_path(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.download_media.return_value = "/data/exports/media/photo/abc.jpg"
        msg = MagicMock()
        result = await telegram_client.download_media(
            message=msg, file_path="/data/exports/media/photo/abc.jpg"
        )
        assert result == "/data/exports/media/photo/abc.jpg"
        raw_client.download_media.assert_awaited_once_with(
            message=msg, file_name="/data/exports/media/photo/abc.jpg"
        )

    async def test_discover_chats_returns_parsed_dialogs(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        chat_a = _make_chat(-100123, "Group A", "supergroup")
        chat_b = _make_chat(456, "User B", "private")
        d_a = MagicMock()
        d_a.chat = chat_a
        d_b = MagicMock()
        d_b.chat = chat_b
        raw_client.get_dialogs = MagicMock()
        raw_client.get_dialogs.return_value = _async_gen([d_a, d_b])
        result = await telegram_client.discover_chats()
        assert len(result) == 2
        assert result[0]["chat_id"] == -100123
        assert result[1]["chat_id"] == 456

    async def test_discover_chats_empty(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.get_dialogs = MagicMock()
        raw_client.get_dialogs.return_value = _async_gen([])
        result = await telegram_client.discover_chats()
        assert result == []

    async def test_download_media_raises_on_failure(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.download_media.return_value = None
        with pytest.raises(RuntimeError, match="download_media returned None"):
            await telegram_client.download_media(
                message=MagicMock(), file_path="/path/file.jpg"
            )


class TestParseMode:
    def test_returns_none_when_input_is_none(self) -> None:
        assert _parse_mode(None) is None

    def test_returns_parse_mode_markdown(self) -> None:
        from pyrogram.enums import ParseMode

        assert _parse_mode("markdown") == ParseMode.MARKDOWN

    def test_returns_parse_mode_html(self) -> None:
        from pyrogram.enums import ParseMode

        assert _parse_mode("html") == ParseMode.HTML

    def test_returns_parse_mode_disabled(self) -> None:
        from pyrogram.enums import ParseMode

        assert _parse_mode("disabled") == ParseMode.DISABLED


class TestClientProperties:
    def test_bot_id(self, telegram_client: TelegramClient) -> None:
        assert telegram_client.bot_id == "testbot"

    def test_is_user_bot_with_token(self, telegram_client: TelegramClient) -> None:
        assert telegram_client.is_user is False

    def test_is_user_user_without_token(self, user_client: TelegramClient) -> None:
        user_client._bot_token = None
        assert user_client.is_user is True

    def test_set_event_callback(self, telegram_client: TelegramClient) -> None:
        cb_called = False

        async def cb(event: Any, ctx: Any) -> None:
            nonlocal cb_called
            cb_called = True

        telegram_client.set_event_callback(cb)
        assert telegram_client._event_callback is cb

    async def test_health_connected(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.is_connected = True
        assert await telegram_client.health() is True

    async def test_health_disconnected(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.is_connected = False
        assert await telegram_client.health() is False

    async def test_health_client_none_returns_false(
        self, telegram_client: TelegramClient
    ) -> None:
        telegram_client._client = None
        assert await telegram_client.health() is False

    def test_get_dialogs_returns_known_chats(
        self, telegram_client: TelegramClient
    ) -> None:
        chat = _make_chat(-100123, "Group A", "supergroup")
        telegram_client._register_chat(chat)
        result = telegram_client.known_chats
        assert len(result) == 1
        assert result[0]["title"] == "Group A"


class TestSendMethodsNoneResults:
    async def test_send_text_raises_on_none(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.send_message.return_value = None
        with pytest.raises(RuntimeError, match="send_message returned None"):
            await telegram_client.send_text(chat_id=1, text="hi")

    async def test_send_photo_raises_on_none(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.send_photo.return_value = None
        with pytest.raises(RuntimeError, match="send_photo returned None"):
            await telegram_client.send_photo(chat_id=1, photo="p.jpg")

    async def test_send_document_raises_on_none(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.send_document.return_value = None
        with pytest.raises(RuntimeError, match="send_document returned None"):
            await telegram_client.send_document(chat_id=1, document="d.pdf")

    async def test_send_video_raises_on_none(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.send_video.return_value = None
        with pytest.raises(RuntimeError, match="send_video returned None"):
            await telegram_client.send_video(chat_id=1, video="v.mp4")

    async def test_send_audio_raises_on_none(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.send_audio.return_value = None
        with pytest.raises(RuntimeError, match="send_audio returned None"):
            await telegram_client.send_audio(chat_id=1, audio="a.mp3")

    async def test_edit_message_text_raises_on_none(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.edit_message_text.return_value = None
        with pytest.raises(RuntimeError, match="edit_message_text returned None"):
            await telegram_client.edit_message_text(chat_id=1, message_id=2, text="x")

    async def test_edit_message_reply_markup_raises_on_none(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.edit_message_reply_markup.return_value = None
        with pytest.raises(
            RuntimeError, match="edit_message_reply_markup returned None"
        ):
            await telegram_client.edit_message_reply_markup(chat_id=1, message_id=2)

    async def test_answer_callback_query_raises_on_unexpected_result(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.answer_callback_query.return_value = "unexpected"
        with pytest.raises(
            RuntimeError, match="answer_callback_query returned unexpected"
        ):
            await telegram_client.answer_callback_query(callback_query_id="cb1")


class TestSendMethodsForwardArgs:
    async def test_send_text_with_parse_mode(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        msg = MagicMock()
        msg.id = 1
        raw_client.send_message.return_value = msg
        result = await telegram_client.send_text(
            chat_id=1, text="**bold**", parse_mode="markdown"
        )
        assert result is msg
        call_kwargs = raw_client.send_message.await_args.kwargs
        assert call_kwargs["parse_mode"] is not None

    async def test_send_text_with_reply_markup(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        msg = MagicMock()
        msg.id = 1
        raw_client.send_message.return_value = msg
        result = await telegram_client.send_text(
            chat_id=1,
            text="hi",
            reply_markup=[[{"text": "btn", "callback_data": "x"}]],
        )
        assert result is msg
        call_kwargs = raw_client.send_message.await_args.kwargs
        assert "reply_markup" in call_kwargs


class TestSendMediaGroupValidation:
    async def test_missing_type_field(self, telegram_client: TelegramClient) -> None:
        with pytest.raises(ValueError, match="missing 'type' field"):
            await telegram_client.send_media_group(
                chat_id=1, media=[{"media": "x.jpg"}]
            )

    async def test_unsupported_type(self, telegram_client: TelegramClient) -> None:
        with pytest.raises(ValueError, match="unsupported type"):
            await telegram_client.send_media_group(
                chat_id=1, media=[{"type": "sticker", "media": "x.webp"}]
            )

    async def test_empty_media_field_photo(
        self, telegram_client: TelegramClient
    ) -> None:
        with pytest.raises(ValueError, match="'media' field is empty"):
            await telegram_client.send_media_group(
                chat_id=1, media=[{"type": "photo", "media": ""}]
            )

    async def test_empty_media_field_video(
        self, telegram_client: TelegramClient
    ) -> None:
        with pytest.raises(ValueError, match="'media' field is empty"):
            await telegram_client.send_media_group(
                chat_id=1, media=[{"type": "video", "media": ""}]
            )

    async def test_empty_list_returns_empty(
        self, telegram_client: TelegramClient
    ) -> None:
        result = await telegram_client.send_media_group(chat_id=1, media=[])
        assert result == []


class TestDownloadAndDelete:
    async def test_download_media_in_memory_raises_on_none(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.download_media.return_value = None
        with pytest.raises(
            RuntimeError, match="download_media_in_memory returned None"
        ):
            await telegram_client.download_media_in_memory("file_1")

    async def test_download_media_in_memory_returns_bytesio(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        buf = io.BytesIO(b"image data")
        raw_client.download_media.return_value = buf
        result = await telegram_client.download_media_in_memory("file_1")
        raw_client.download_media.assert_awaited_once_with("file_1", in_memory=True)
        assert result is buf

    async def test_delete_message_happy_path(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.delete_messages.return_value = True
        await telegram_client.delete_message(chat_id=1, message_ids=10)
        raw_client.delete_messages.assert_awaited_once_with(chat_id=1, message_ids=10)


class TestStop:
    async def test_stop_happy_path(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.stop = AsyncMock()
        await telegram_client.stop()
        raw_client.stop.assert_awaited_once()

    async def test_stop_raises_error(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.stop = AsyncMock(side_effect=ConnectionError("gone"))
        with pytest.raises(ConnectionError):
            await telegram_client.stop()


class TestBotCommands:
    async def test_set_bot_commands_happy_path(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.set_bot_commands = AsyncMock()
        commands = [("start", "Start the bot"), ("help", "Get help")]
        await telegram_client.set_bot_commands(commands)
        raw_client.set_bot_commands.assert_awaited_once()
        call_args = raw_client.set_bot_commands.await_args.args

        assert len(call_args[0]) == 2
        assert call_args[0][0].command == "start"
        assert call_args[0][0].description == "Start the bot"

    async def test_set_bot_commands_raises_error(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.set_bot_commands = AsyncMock(side_effect=RuntimeError("bad request"))
        with pytest.raises(RuntimeError, match="bad request"):
            await telegram_client.set_bot_commands([("x", "y")])


class TestRegisterChat:
    def test_register_chat_no_title_uses_first_last(
        self, telegram_client: TelegramClient
    ) -> None:
        chat = MagicMock()
        chat.id = 123
        chat.title = ""
        chat.first_name = "John"
        chat.last_name = "Doe"
        chat.type = "ChatType.PRIVATE"
        chat.member_count = 0
        chat.permissions = None
        telegram_client._register_chat(chat)
        entry = telegram_client._known_chats[123]
        assert entry["title"] == "John Doe"

    def test_register_chat_no_title_no_last(
        self, telegram_client: TelegramClient
    ) -> None:
        chat = MagicMock()
        chat.id = 124
        chat.title = ""
        chat.first_name = "Alice"
        chat.last_name = ""
        chat.type = "ChatType.PRIVATE"
        chat.member_count = 0
        chat.permissions = None
        telegram_client._register_chat(chat)
        entry = telegram_client._known_chats[124]
        assert entry["title"] == "Alice"

    def test_register_chat_none_chat_type(
        self, telegram_client: TelegramClient
    ) -> None:
        chat = MagicMock()
        chat.id = 125
        chat.title = "Test"
        chat.type = None
        chat.member_count = 0
        chat.permissions = None
        telegram_client._register_chat(chat)
        entry = telegram_client._known_chats[125]
        assert entry["type"] == "unknown"


class TestSendMediaGroupHappyPath:
    async def test_send_media_group_photo(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        msg_a = MagicMock()
        msg_a.message_id = 1
        raw_client.send_media_group.return_value = [msg_a]
        result = await telegram_client.send_media_group(
            chat_id=1, media=[{"type": "photo", "media": "file.jpg"}]
        )
        assert result == [msg_a]
        args = raw_client.send_media_group.await_args
        assert args.kwargs["chat_id"] == 1
        from pyrogram.types import InputMediaPhoto

        assert isinstance(args.kwargs["media"][0], InputMediaPhoto)

    async def test_send_media_group_video(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        msg = MagicMock()
        raw_client.send_media_group.return_value = [msg]
        await telegram_client.send_media_group(
            chat_id=2, media=[{"type": "video", "media": "vid.mp4"}]
        )
        from pyrogram.types import InputMediaVideo

        assert isinstance(
            raw_client.send_media_group.await_args.kwargs["media"][0],
            InputMediaVideo,
        )

    async def test_send_media_group_with_reply_to(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.send_media_group.return_value = []
        await telegram_client.send_media_group(
            chat_id=1,
            media=[{"type": "photo", "media": "f.jpg"}],
            reply_to_message_id=42,
        )
        assert (
            raw_client.send_media_group.await_args.kwargs["reply_to_message_id"] == 42
        )


class TestAnswerCallbackQueryHappyPath:
    async def test_answer_callback_query_returns_true_on_none(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.answer_callback_query.return_value = None
        result = await telegram_client.answer_callback_query("cb_1")
        assert result is True

    async def test_answer_callback_query_with_text_and_url(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.answer_callback_query.return_value = None
        result = await telegram_client.answer_callback_query(
            "cb_2", text="ok", url="https://t.me/example", show_alert=True
        )
        assert result is True
        call_kwargs = raw_client.answer_callback_query.await_args.kwargs
        assert call_kwargs["text"] == "ok"
        assert call_kwargs["url"] == "https://t.me/example"
        assert call_kwargs["show_alert"] is True


class TestEventHandlerNoCallback:
    async def test_on_message_no_callback(
        self, telegram_client: TelegramClient
    ) -> None:
        msg = MagicMock()
        result = await telegram_client._on_message(telegram_client._client, msg)
        assert result is None

    async def test_on_callback_query_no_callback(
        self, telegram_client: TelegramClient
    ) -> None:
        query = MagicMock()
        query.message = None
        result = await telegram_client._on_callback_query(
            telegram_client._client, query
        )
        assert result is None

    async def test_on_edited_message_no_callback(
        self, telegram_client: TelegramClient
    ) -> None:
        msg = MagicMock()
        result = await telegram_client._on_edited_message(telegram_client._client, msg)
        assert result is None

    async def test_on_reaction_updated_no_callback(
        self, telegram_client: TelegramClient
    ) -> None:
        reaction = MagicMock()
        reaction.chat = None
        result = await telegram_client._on_message_reaction_updated(
            telegram_client._client, reaction
        )
        assert result is None

    async def test_on_reaction_count_updated_no_callback(
        self, telegram_client: TelegramClient
    ) -> None:
        reaction = MagicMock()
        reaction.chat = None
        result = await telegram_client._on_message_reaction_count_updated(
            telegram_client._client, reaction
        )
        assert result is None


class TestConnectHandlers:
    async def test_on_connect_calls_callback(
        self, telegram_client: TelegramClient
    ) -> None:
        cb_called = False

        async def on_connect() -> None:
            nonlocal cb_called
            cb_called = True

        telegram_client._on_connect_cb = on_connect
        await telegram_client._on_connect_handler()
        assert cb_called is True

    async def test_on_connect_no_callback(
        self, telegram_client: TelegramClient
    ) -> None:
        telegram_client._on_connect_cb = None
        await telegram_client._on_connect_handler()

    async def test_on_disconnect_calls_callback(
        self, telegram_client: TelegramClient
    ) -> None:
        cb_called = False

        async def on_disconnect() -> None:
            nonlocal cb_called
            cb_called = True

        telegram_client._on_disconnect_cb = on_disconnect
        await telegram_client._on_disconnect_handler(telegram_client._client)
        assert cb_called is True

    async def test_on_disconnect_no_callback(
        self, telegram_client: TelegramClient
    ) -> None:
        telegram_client._on_disconnect_cb = None
        await telegram_client._on_disconnect_handler(telegram_client._client)
