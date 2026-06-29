from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.media_downloader import MediaDownloader
from domain.entities import (
    ChatType,
    CommandEvent,
    MessageEvent,
    RoutingContext,
)
from infrastructure.media.storage import MediaStorage


@pytest.fixture
def storage() -> MagicMock:
    m = MagicMock(spec=MediaStorage)
    m.retrieve = AsyncMock(return_value=None)
    m.store = AsyncMock()
    return m


@pytest.fixture
def config() -> MagicMock:
    m = MagicMock()
    m.evaluate.return_value = True
    return m


@pytest.fixture
def clients() -> dict[str, Any]:
    client = MagicMock()
    client._client = MagicMock()
    client._client.is_connected = True
    client._client.download_media = AsyncMock(
        return_value=io.BytesIO(b"fake_media_bytes")
    )
    return {"aibot": client}


@pytest.fixture
def downloader(
    storage: MagicMock,
    config: MagicMock,
    clients: dict[str, Any],
) -> MediaDownloader:
    return MediaDownloader(
        storage=storage,
        clients=clients,
        config=config,
    )


def _photo_event(**overrides: Any) -> MessageEvent:
    kwargs: dict[str, Any] = dict(
        event_id=str(uuid4()),
        timestamp=datetime.now(timezone.utc),
        bot_id="aibot",
        chat_id=12345,
        user_id=67890,
        message_id=101,
        text=None,
        has_media=True,
        media_type="photo",
        file_id="file_id_abc",
        file_unique_id="fuid_abc",
    )
    kwargs.update(overrides)
    return MessageEvent(**kwargs)


def _media_context(**overrides: Any) -> RoutingContext:
    return RoutingContext(
        chat_type=ChatType.PRIVATE,
        has_media=True,
        media_type="photo",
        **overrides,
    )


class TestMediaDownloader:
    async def test_not_message_event_skipped(
        self,
        downloader: MediaDownloader,
        config: MagicMock,
        storage: MagicMock,
    ) -> None:
        event = CommandEvent(
            event_id=str(uuid4()),
            timestamp=datetime.now(timezone.utc),
            bot_id="aibot",
            chat_id=12345,
            user_id=67890,
            message_id=1,
            command="start",
            command_args=[],
            text="/start",
        )
        context = RoutingContext(chat_type=ChatType.PRIVATE)
        await downloader.on_event(event, context)
        config.evaluate.assert_not_called()
        storage.store.assert_not_awaited()

    async def test_no_media_skipped(
        self,
        downloader: MediaDownloader,
        config: MagicMock,
        storage: MagicMock,
    ) -> None:
        event = MessageEvent(
            event_id=str(uuid4()),
            timestamp=datetime.now(timezone.utc),
            bot_id="aibot",
            chat_id=12345,
            user_id=67890,
            message_id=1,
            text="hello",
        )
        context = RoutingContext(chat_type=ChatType.PRIVATE)
        await downloader.on_event(event, context)
        config.evaluate.assert_not_called()
        storage.store.assert_not_awaited()

    async def test_no_file_id_skipped(
        self,
        downloader: MediaDownloader,
        config: MagicMock,
        storage: MagicMock,
    ) -> None:
        event = MessageEvent(
            event_id=str(uuid4()),
            timestamp=datetime.now(timezone.utc),
            bot_id="aibot",
            chat_id=12345,
            user_id=67890,
            message_id=1,
            text=None,
            has_media=True,
            media_type="photo",
            file_id=None,
            file_unique_id=None,
        )
        context = RoutingContext(
            chat_type=ChatType.PRIVATE, has_media=True, media_type="photo"
        )
        await downloader.on_event(event, context)
        config.evaluate.assert_not_called()
        storage.store.assert_not_awaited()

    async def test_lazy_skips_download(
        self,
        downloader: MediaDownloader,
        config: MagicMock,
        storage: MagicMock,
    ) -> None:
        config.evaluate.return_value = False
        event = _photo_event()
        context = _media_context()
        await downloader.on_event(event, context)
        config.evaluate.assert_called_once_with(
            chat_id=12345, user_id=67890, media_type="photo"
        )
        storage.store.assert_not_awaited()

    async def test_already_cached_skips_download(
        self,
        downloader: MediaDownloader,
        config: MagicMock,
        storage: MagicMock,
        clients: dict[str, Any],
    ) -> None:
        storage.retrieve.return_value = b"cached data"
        event = _photo_event()
        context = _media_context()
        await downloader.on_event(event, context)
        config.evaluate.assert_called_once()
        storage.retrieve.assert_awaited_once_with("aibot", "fuid_abc")
        await asyncio.sleep(0)
        storage.store.assert_not_awaited()

    async def test_eager_triggers_download_and_store(
        self,
        downloader: MediaDownloader,
        config: MagicMock,
        storage: MagicMock,
        clients: dict[str, Any],
    ) -> None:
        event = _photo_event()
        context = _media_context()
        await downloader.on_event(event, context)
        config.evaluate.assert_called_once()
        storage.retrieve.assert_awaited_once_with("aibot", "fuid_abc")
        await asyncio.sleep(0)
        storage.store.assert_awaited_once()
        call_args = storage.store.await_args
        assert call_args is not None
        assert call_args.args[0] == "aibot"
        assert call_args.args[1] == "fuid_abc"

    async def test_download_client_not_found(
        self,
        downloader: MediaDownloader,
        config: MagicMock,
        storage: MagicMock,
    ) -> None:
        event = _photo_event(bot_id="unknown_bot")
        context = _media_context()
        await downloader.on_event(event, context)
        config.evaluate.assert_called_once()
        await asyncio.sleep(0)
        storage.store.assert_not_awaited()
