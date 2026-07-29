from __future__ import annotations

import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from infrastructure.media.endpoint import handle_file_get
from infrastructure.media.upload_routes import ClientMapKey, StorageKey


def _make_request(
    bot_id: str | None = "mybot",
    file_unique_id: str | None = "file123",
    file_id: str | None = None,
    storage: Any = None,
    client_map: dict[str, Any] | None = None,
) -> web.Request:
    app = web.Application()
    if storage is not None:
        app[StorageKey] = storage
    if client_map is not None:
        app[ClientMapKey] = client_map

    req = MagicMock(spec=web.Request, app=app)
    req.match_info = {"bot_id": bot_id, "file_unique_id": file_unique_id}
    req.query = {"file_id": file_id} if file_id else {}
    return req


@pytest.fixture
def mock_storage() -> MagicMock:
    s = MagicMock()
    s.retrieve = AsyncMock()
    s.path_for = AsyncMock()
    s.store = AsyncMock()
    return s


@pytest.fixture
def mock_client() -> MagicMock:
    c = MagicMock()
    c.download_media_in_memory = AsyncMock()
    return c


class TestValidationErrors:
    async def test_missing_bot_id(self) -> None:
        resp = await handle_file_get(_make_request(bot_id=None))
        assert resp.status == 400
        assert b"missing bot_id" in (resp.body or b"")

    async def test_missing_file_unique_id(self) -> None:
        resp = await handle_file_get(_make_request(file_unique_id=None))
        assert resp.status == 400
        assert b"missing file_unique_id" in (resp.body or b"")

    async def test_storage_not_available(self) -> None:
        resp = await handle_file_get(_make_request(storage=None))
        assert resp.status == 503
        assert b"storage not available" in (resp.body or b"")


class TestCacheHit:
    async def test_cache_hit_returns_file(self, mock_storage: MagicMock) -> None:
        mock_storage.retrieve.return_value = b"cached data"
        mock_storage.path_for.return_value = MagicMock()
        mock_storage.path_for.return_value.exists.return_value = True
        mock_storage.path_for.return_value.suffix = ".jpg"

        resp = await handle_file_get(_make_request(storage=mock_storage))
        assert resp.status == 200
        assert resp.body == b"cached data"
        assert resp.content_type == "image/jpeg"

    async def test_cache_hit_png(self, mock_storage: MagicMock) -> None:
        mock_storage.retrieve.return_value = b"png data"
        mock_storage.path_for.return_value = MagicMock()
        mock_storage.path_for.return_value.exists.return_value = True
        mock_storage.path_for.return_value.suffix = ".png"

        resp = await handle_file_get(_make_request(storage=mock_storage))
        assert resp.status == 200
        assert resp.content_type == "image/png"

    async def test_cache_hit_path_for_none(self, mock_storage: MagicMock) -> None:
        mock_storage.retrieve.return_value = b"data"
        mock_storage.path_for.return_value = None

        resp = await handle_file_get(_make_request(storage=mock_storage))
        assert resp.status == 500
        assert b"cached file has no path" in (resp.body or b"")

    async def test_cache_hit_path_not_exist(self, mock_storage: MagicMock) -> None:
        mock_storage.retrieve.return_value = b"data"
        mock_storage.path_for.return_value = MagicMock()
        mock_storage.path_for.return_value.exists.return_value = False

        resp = await handle_file_get(_make_request(storage=mock_storage))
        assert resp.status == 500
        assert b"cached file path does not exist" in (resp.body or b"")

    async def test_cache_hit_no_extension(self, mock_storage: MagicMock) -> None:
        mock_storage.retrieve.return_value = b"data"
        mock_storage.path_for.return_value = MagicMock()
        mock_storage.path_for.return_value.exists.return_value = True
        mock_storage.path_for.return_value.suffix = ""

        resp = await handle_file_get(_make_request(storage=mock_storage))
        assert resp.status == 500
        assert b"cached file has no extension" in (resp.body or b"")


class TestCacheMiss:
    async def test_no_file_id_provided(self, mock_storage: MagicMock) -> None:
        mock_storage.retrieve.return_value = None

        resp = await handle_file_get(_make_request(storage=mock_storage))
        assert resp.status == 404
        assert b"file not cached and no file_id" in (resp.body or b"")

    async def test_client_map_not_available(self, mock_storage: MagicMock) -> None:
        mock_storage.retrieve.return_value = None

        resp = await handle_file_get(
            _make_request(storage=mock_storage, file_id="AgAC123")
        )
        assert resp.status == 503
        assert b"client_map not available" in (resp.body or b"")

    async def test_unknown_bot(self, mock_storage: MagicMock) -> None:
        mock_storage.retrieve.return_value = None

        resp = await handle_file_get(
            _make_request(
                storage=mock_storage,
                file_id="AgAC123",
                client_map={"otherbot": MagicMock()},
            )
        )
        assert resp.status == 404
        assert b"unknown bot: mybot" in (resp.body or b"")

    async def test_download_failure(
        self,
        mock_storage: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        mock_storage.retrieve.return_value = None
        mock_client.download_media_in_memory.side_effect = RuntimeError("TG fail")

        resp = await handle_file_get(
            _make_request(
                storage=mock_storage,
                file_id="AgAC123",
                client_map={"mybot": mock_client},
            )
        )
        assert resp.status == 502
        assert b"telegram download failed" in (resp.body or b"")

    async def test_store_failure(
        self,
        mock_storage: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        mock_storage.retrieve.return_value = None
        buf = io.BytesIO(b"downloaded data")
        mock_client.download_media_in_memory.return_value = buf
        mock_storage.store.return_value = ""

        resp = await handle_file_get(
            _make_request(
                storage=mock_storage,
                file_id="AgAC123",
                client_map={"mybot": mock_client},
            )
        )
        assert resp.status == 500
        assert b"failed to store file" in (resp.body or b"")

    async def test_store_verify_retrieve_failure(
        self,
        mock_storage: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        mock_storage.retrieve.side_effect = [None, None]
        buf = io.BytesIO(b"downloaded data")
        mock_client.download_media_in_memory.return_value = buf
        mock_storage.store.return_value = "/tmp/some.jpg"

        resp = await handle_file_get(
            _make_request(
                storage=mock_storage,
                file_id="AgAC123",
                client_map={"mybot": mock_client},
            )
        )
        assert resp.status == 500
        assert b"storage verification failed" in (resp.body or b"")

    async def test_store_verify_path_failure(
        self,
        mock_storage: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        mock_storage.retrieve.side_effect = [None, b"ok_data"]
        buf = io.BytesIO(b"downloaded data")
        mock_client.download_media_in_memory.return_value = buf
        mock_storage.store.return_value = "/tmp/some.jpg"
        mock_storage.path_for.return_value = None

        resp = await handle_file_get(
            _make_request(
                storage=mock_storage,
                file_id="AgAC123",
                client_map={"mybot": mock_client},
            )
        )
        assert resp.status == 500
        assert b"storage verification path failed" in (resp.body or b"")

    async def test_successful_download_and_cache(
        self,
        mock_storage: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        mock_storage.retrieve.side_effect = [None, b"ok_data"]
        buf = io.BytesIO(b"fresh telegram data")
        mock_client.download_media_in_memory.return_value = buf
        mock_storage.store.return_value = "/tmp/some.bin"
        path_mock = MagicMock()
        path_mock.exists.return_value = True
        mock_storage.path_for.return_value = path_mock

        resp = await handle_file_get(
            _make_request(
                storage=mock_storage,
                file_id="AgAC123",
                client_map={"mybot": mock_client},
            )
        )
        assert resp.status == 200
        assert resp.body == b"fresh telegram data"
        mock_client.download_media_in_memory.assert_awaited_once_with("AgAC123")
        mock_storage.store.assert_awaited_once()
