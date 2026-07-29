from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.media_config import MediaConfigManager
from app.media_downloader import MediaDownloader
from domain.entities import (
    CommandEvent,
    MessageEvent,
    RoutingContext,
)


@pytest.fixture
def mock_storage() -> MagicMock:
    s = MagicMock()
    s.retrieve = AsyncMock()
    s.store = AsyncMock()
    return s


@pytest.fixture
def mock_config() -> MediaConfigManager:
    m = MagicMock(spec=MediaConfigManager)
    m.evaluate = MagicMock(return_value=True)
    return m


@pytest.fixture
def mock_publisher() -> MagicMock:
    p = MagicMock()
    p.publish = AsyncMock()
    return p


@pytest.fixture
def mock_client() -> MagicMock:
    c = MagicMock()
    c._client = MagicMock()
    c._client.is_connected = True
    c._client.download_media = AsyncMock()
    return c


@pytest.fixture
def downloader(
    mock_storage: MagicMock,
    mock_config: MediaConfigManager,
    mock_publisher: MagicMock,
    mock_client: MagicMock,
) -> MediaDownloader:
    return MediaDownloader(
        storage=mock_storage,
        clients={"testbot": mock_client},
        config=mock_config,
        publisher=mock_publisher,
        media_base_url="http://localhost:8080",
    )


def _msg_event(**kw: object) -> MessageEvent:
    defaults: dict[str, object] = dict(
        event_id="ev1",
        bot_id="testbot",
        chat_id=1,
        user_id=2,
        message_id=10,
        has_media=True,
        file_id="AgAC_file",
        file_unique_id="QQAD_unique",
    )
    defaults.update(kw)
    return MessageEvent(**defaults)


def _ctx(**kw: object) -> RoutingContext:
    defaults: dict[str, object] = dict(
        chat_type="private",
        media_type="photo",
    )
    defaults.update(kw)
    return RoutingContext(**defaults)


class TestOnEventEarlyReturns:
    async def test_not_message_event(self, downloader: MediaDownloader) -> None:
        evt = CommandEvent(
            event_id="ev",
            bot_id="testbot",
            chat_id=1,
            user_id=2,
            message_id=10,
            command="start",
            text="/start",
        )
        await downloader.on_event(evt, _ctx())
        downloader._storage.retrieve.assert_not_called()

    async def test_no_media(self, downloader: MediaDownloader) -> None:
        await downloader.on_event(_msg_event(has_media=False), _ctx())
        downloader._storage.retrieve.assert_not_called()

    async def test_no_media_type(self, downloader: MediaDownloader) -> None:
        await downloader.on_event(_msg_event(), _ctx(media_type=None))
        downloader._storage.retrieve.assert_not_called()

    async def test_no_file_id_or_unique(self, downloader: MediaDownloader) -> None:
        await downloader.on_event(_msg_event(file_id=None, file_unique_id=None), _ctx())
        downloader._storage.retrieve.assert_not_called()

    async def test_lazy_mode_skip(self, downloader: MediaDownloader) -> None:
        downloader._config.evaluate.return_value = False
        await downloader.on_event(_msg_event(), _ctx())
        downloader._storage.retrieve.assert_not_called()

    async def test_already_cached(self, downloader: MediaDownloader) -> None:
        downloader._storage.retrieve.return_value = b"exists"
        await downloader.on_event(_msg_event(), _ctx())
        downloader._storage.retrieve.assert_awaited_once()


class TestDownloadEarlyReturns:
    async def test_no_file_id(self, downloader: MediaDownloader) -> None:
        await downloader._download(_msg_event(file_id=None), _ctx())
        downloader._storage.store.assert_not_called()

    async def test_no_file_unique_id(self, downloader: MediaDownloader) -> None:
        await downloader._download(_msg_event(file_unique_id=None), _ctx())
        downloader._storage.store.assert_not_called()

    async def test_client_not_found(self, downloader: MediaDownloader) -> None:
        evt = _msg_event(bot_id="unknownbot")
        await downloader._download(evt, _ctx())
        downloader._storage.store.assert_not_called()

    async def test_client_inner_none(
        self, downloader: MediaDownloader, mock_client: MagicMock
    ) -> None:
        mock_client._client = None
        await downloader._download(_msg_event(), _ctx())
        downloader._storage.store.assert_not_called()

    async def test_client_disconnected(
        self, downloader: MediaDownloader, mock_client: MagicMock
    ) -> None:
        mock_client._client.is_connected = False
        await downloader._download(_msg_event(), _ctx())
        downloader._storage.store.assert_not_called()


class TestDownloadPaths:
    async def test_download_exception(
        self, downloader: MediaDownloader, mock_client: MagicMock
    ) -> None:
        mock_client._client.download_media.side_effect = RuntimeError("boom")
        await downloader._download(_msg_event(), _ctx())
        downloader._storage.store.assert_not_called()

    async def test_result_is_none(
        self, downloader: MediaDownloader, mock_client: MagicMock
    ) -> None:
        mock_client._client.download_media.return_value = None
        await downloader._download(_msg_event(), _ctx())
        downloader._storage.store.assert_not_called()

    async def test_unsupported_result_type(
        self, downloader: MediaDownloader, mock_client: MagicMock
    ) -> None:
        mock_client._client.download_media.return_value = 42
        await downloader._download(_msg_event(), _ctx())
        downloader._storage.store.assert_not_called()

    async def test_result_bytes(
        self, downloader: MediaDownloader, mock_client: MagicMock
    ) -> None:
        mock_client._client.download_media.return_value = b"raw bytes"
        downloader._storage.store.return_value = "/path/file.jpg"
        await downloader._download(_msg_event(), _ctx())
        downloader._storage.store.assert_awaited_once_with(
            "testbot", "QQAD_unique", b"raw bytes", "jpg"
        )
        downloader._publisher.publish.assert_awaited_once()

    async def test_result_bytesio(
        self, downloader: MediaDownloader, mock_client: MagicMock
    ) -> None:
        import io

        buf = io.BytesIO(b"bytesio data")
        mock_client._client.download_media.return_value = buf
        downloader._storage.store.return_value = "/path/file.jpg"
        await downloader._download(_msg_event(), _ctx())
        downloader._storage.store.assert_awaited_once_with(
            "testbot", "QQAD_unique", b"bytesio data", "jpg"
        )

    async def test_result_filelike(
        self, downloader: MediaDownloader, mock_client: MagicMock
    ) -> None:
        f = MagicMock(spec=["read"])
        f.read.return_value = b"file data"
        mock_client._client.download_media.return_value = f
        downloader._storage.store.return_value = "/path/file.jpg"
        await downloader._download(_msg_event(), _ctx())
        downloader._storage.store.assert_awaited_once_with(
            "testbot", "QQAD_unique", b"file data", "jpg"
        )


class TestDownloadPublisher:
    async def test_no_publisher_skips(
        self,
        mock_storage: MagicMock,
        mock_config: MediaConfigManager,
        mock_client: MagicMock,
    ) -> None:
        d = MediaDownloader(
            storage=mock_storage,
            clients={"testbot": mock_client},
            config=mock_config,
            publisher=None,
        )
        mock_client._client.download_media.return_value = b"data"
        mock_storage.store.return_value = "/path/file.jpg"
        await d._download(_msg_event(), _ctx())
        mock_storage.store.assert_awaited_once()

    async def test_publish_failure_logged(
        self,
        downloader: MediaDownloader,
        mock_client: MagicMock,
        mock_publisher: MagicMock,
    ) -> None:
        mock_client._client.download_media.return_value = b"data"
        downloader._storage.store.return_value = "/path/file.jpg"
        mock_publisher.publish.side_effect = RuntimeError("publish fail")
        await downloader._download(_msg_event(), _ctx())
        downloader._storage.store.assert_awaited_once()

    async def test_unsupported_ext_raises(
        self, downloader: MediaDownloader, mock_client: MagicMock
    ) -> None:
        mock_client._client.download_media.return_value = b"data"
        with pytest.raises(ValueError, match="Unsupported media type"):
            await downloader._download(_msg_event(), _ctx(media_type="unknown_type"))
