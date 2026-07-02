from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.config import BotConfig
from infrastructure.telegram.client import TelegramClient


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
    return client


@pytest.fixture
def bot_config() -> BotConfig:
    return BotConfig(
        name="testbot",
        api_id=12345,
        api_hash="abc123",
        session_file="sessions/test.session",
    )


@pytest.fixture
def telegram_client(raw_client: MagicMock, bot_config: BotConfig) -> TelegramClient:
    tc = TelegramClient(config=bot_config)
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

    async def test_download_media_returns_none_on_failure(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.download_media.return_value = None
        result = await telegram_client.download_media(
            message=MagicMock(), file_path="/path/file.jpg"
        )
        assert result is None
