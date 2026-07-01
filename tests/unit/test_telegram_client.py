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
    client.get_dialogs = MagicMock()
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


class MockChat:
    def __init__(self, chat_id: int, title: str, chat_type: str) -> None:
        self.id = chat_id
        self.title = title
        self.first_name = None
        self.last_name = None
        self.type = MagicMock()
        self.type.value = chat_type.upper()
        self.member_count = 42
        self.permissions = MagicMock()
        self.permissions.can_send_messages = True


def _make_dialog(chat_id: int, title: str, chat_type: str) -> MagicMock:
    dialog = MagicMock()
    dialog.chat = MockChat(chat_id, title, chat_type)
    return dialog


class TestTelegramClientExport:
    async def test_get_dialogs_returns_list(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.get_dialogs.return_value = _async_gen(
            [
                _make_dialog(-100123, "Group A", "group"),
                _make_dialog(456, "User B", "private"),
            ]
        )
        result = await telegram_client.get_dialogs()
        assert len(result) == 2
        assert result[0]["chat_id"] == -100123
        assert result[0]["title"] == "Group A"
        assert result[1]["chat_id"] == 456

    async def test_get_dialogs_empty(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.get_dialogs.return_value = _async_gen([])
        result = await telegram_client.get_dialogs()
        assert result == []

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

    async def test_download_media_returns_none_on_failure(
        self, telegram_client: TelegramClient, raw_client: MagicMock
    ) -> None:
        raw_client.download_media.return_value = None
        result = await telegram_client.download_media(
            message=MagicMock(), file_path="/path/file.jpg"
        )
        assert result is None
