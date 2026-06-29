from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from domain.schemas import UploadEntry
from infrastructure.media.upload_routes import (
    ClientMapKey,
    MaxUploadSizeKey,
    MediaStorageKey,
    UploadRegistryKey,
    handle_upload_post,
)
from infrastructure.sqlite import UploadRegistry


def _make_app(
    registry: UploadRegistry | None,
    storage: MagicMock | None = None,
    client_map: dict[str, Any] | None = None,
    max_size: int = 2000 * 1024 * 1024,
) -> web.Application:
    app = web.Application()
    if registry is not None:
        app[UploadRegistryKey] = registry
    if storage is not None:
        app[MediaStorageKey] = storage
    app[ClientMapKey] = client_map or {}
    app[MaxUploadSizeKey] = max_size
    app.router.add_post("/upload/{bot_id}", handle_upload_post)
    return app


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def reg_and_storage() -> tuple[UploadRegistry, MagicMock, TemporaryDirectory[str]]:
    tmp = TemporaryDirectory()
    db_path = str(Path(tmp.name) / "uploads.db")
    reg = UploadRegistry(db_path)
    reg.connect()

    storage = MagicMock()
    storage.store = AsyncMock(return_value=str(Path(tmp.name) / "file.bin"))
    storage.path_for = AsyncMock(return_value=None)

    return reg, storage, tmp


def _upload(
    data: bytes,
    filename: str = "file",
    content_type: str | None = None,
) -> FormData:
    fd = FormData()
    kwargs: dict[str, Any] = {"filename": filename}
    if content_type:
        kwargs["content_type"] = content_type
    fd.add_field("file", data, **kwargs)
    return fd


class TestHandleUploadPost:
    async def test_missing_bot_id(self) -> None:
        app = _make_app(registry=MagicMock())
        client = TestClient(TestServer(app))
        async with client:
            resp = await client.post("/upload/")
            assert resp.status == 404

    async def test_service_not_available(self) -> None:
        app = _make_app(registry=None)
        client = TestClient(TestServer(app))
        async with client:
            resp = await client.post("/upload/testbot")
            assert resp.status == 503
            data = await resp.json()
            assert "error" in data

    async def test_unknown_bot(self) -> None:
        app = _make_app(registry=MagicMock(), storage=MagicMock(), client_map={})
        client = TestClient(TestServer(app))
        async with client:
            resp = await client.post("/upload/unknown")
            assert resp.status == 404
            data = await resp.json()
            assert "unknown bot" in data["error"]

    async def test_missing_file_field(
        self, reg_and_storage: tuple[UploadRegistry, MagicMock, TemporaryDirectory[str]]
    ) -> None:
        reg, storage, tmp = reg_and_storage
        try:
            app = _make_app(
                registry=reg,
                storage=storage,
                client_map={"aibot": MagicMock()},
            )
            client = TestClient(TestServer(app))
            fd = FormData()
            fd.add_field("wrong_field", b"data", filename="test.txt")
            async with client:
                resp = await client.post("/upload/aibot", data=fd)
                assert resp.status == 400
                data = await resp.json()
                assert "file" in data["error"]
        finally:
            reg.close()
            tmp.cleanup()

    async def test_empty_file(
        self, reg_and_storage: tuple[UploadRegistry, MagicMock, TemporaryDirectory[str]]
    ) -> None:
        reg, storage, tmp = reg_and_storage
        try:
            app = _make_app(
                registry=reg,
                storage=storage,
                client_map={"aibot": MagicMock()},
            )
            client = TestClient(TestServer(app))
            async with client:
                resp = await client.post("/upload/aibot", data=_upload(b""))
                assert resp.status == 400
                data = await resp.json()
                assert "empty" in data["error"]
        finally:
            reg.close()
            tmp.cleanup()

    async def test_file_too_large(
        self, reg_and_storage: tuple[UploadRegistry, MagicMock, TemporaryDirectory[str]]
    ) -> None:
        reg, storage, tmp = reg_and_storage
        try:
            app = _make_app(
                registry=reg,
                storage=storage,
                client_map={"aibot": MagicMock()},
                max_size=10,
            )
            client = TestClient(TestServer(app))
            async with client:
                resp = await client.post("/upload/aibot", data=_upload(b"x" * 100))
                assert resp.status == 413
                data = await resp.json()
                assert "too large" in data["error"]
        finally:
            reg.close()
            tmp.cleanup()

    async def test_successful_upload(
        self, reg_and_storage: tuple[UploadRegistry, MagicMock, TemporaryDirectory[str]]
    ) -> None:
        reg, storage, tmp = reg_and_storage
        try:
            app = _make_app(
                registry=reg,
                storage=storage,
                client_map={"aibot": MagicMock()},
            )
            client = TestClient(TestServer(app))
            async with client:
                payload = b"hello world upload test"
                resp = await client.post("/upload/aibot", data=_upload(payload))
                assert resp.status == 200
                data = await resp.json()
                assert data["upload_id"] == f"upl_{_hash(payload)}"
                assert data["cached"] is False
                assert data["file_id"] is None
                assert data["size"] == len(payload)
                assert data["ext"] == "bin"

            entry = reg.get_by_hash(_hash(payload))
            assert entry is not None
            assert entry.bot_id == "aibot"
            assert entry.size == len(payload)
        finally:
            reg.close()
            tmp.cleanup()

    async def test_detect_ext_from_filename(
        self, reg_and_storage: tuple[UploadRegistry, MagicMock, TemporaryDirectory[str]]
    ) -> None:
        reg, storage, tmp = reg_and_storage
        try:
            app = _make_app(
                registry=reg,
                storage=storage,
                client_map={"aibot": MagicMock()},
            )
            client = TestClient(TestServer(app))
            async with client:
                payload = b"fake jpeg data"
                resp = await client.post(
                    "/upload/aibot", data=_upload(payload, filename="photo.jpg")
                )
                assert resp.status == 200
                data = await resp.json()
                assert data["ext"] == "jpg"
        finally:
            reg.close()
            tmp.cleanup()

    async def test_detect_ext_from_content_type(
        self, reg_and_storage: tuple[UploadRegistry, MagicMock, TemporaryDirectory[str]]
    ) -> None:
        reg, storage, tmp = reg_and_storage
        try:
            app = _make_app(
                registry=reg,
                storage=storage,
                client_map={"aibot": MagicMock()},
            )
            client = TestClient(TestServer(app))
            async with client:
                payload = b"fake png data"
                resp = await client.post(
                    "/upload/aibot",
                    data=_upload(payload, content_type="image/png"),
                )
                assert resp.status == 200
                data = await resp.json()
                assert data["ext"] == "png"
        finally:
            reg.close()
            tmp.cleanup()

    async def test_cache_hit_returns_file_id(
        self, reg_and_storage: tuple[UploadRegistry, MagicMock, TemporaryDirectory[str]]
    ) -> None:
        reg, storage, tmp = reg_and_storage
        try:
            payload = b"cache me"
            content_hash = _hash(payload)
            reg.register(
                UploadEntry(
                    content_hash=content_hash,
                    bot_id="aibot",
                    ext="jpg",
                    size=len(payload),
                )
            )
            reg.update_file_id(content_hash, "AgAC_existing", "QQAD_existing")

            app = _make_app(
                registry=reg,
                storage=storage,
                client_map={"aibot": MagicMock()},
            )
            client = TestClient(TestServer(app))
            async with client:
                resp = await client.post("/upload/aibot", data=_upload(payload))
                assert resp.status == 200
                data = await resp.json()
                assert data["upload_id"] == f"upl_{content_hash}"
                assert data["cached"] is True
                assert data["file_id"] == "AgAC_existing"
                assert data["ext"] == "jpg"

                storage.store.assert_not_called()
        finally:
            reg.close()
            tmp.cleanup()

    async def test_cache_hit_no_file_id(
        self, reg_and_storage: tuple[UploadRegistry, MagicMock, TemporaryDirectory[str]]
    ) -> None:
        reg, storage, tmp = reg_and_storage
        try:
            payload = b"cache no fileid"
            content_hash = _hash(payload)
            reg.register(
                UploadEntry(
                    content_hash=content_hash,
                    bot_id="aibot",
                    ext="bin",
                    size=len(payload),
                )
            )

            app = _make_app(
                registry=reg,
                storage=storage,
                client_map={"aibot": MagicMock()},
            )
            client = TestClient(TestServer(app))
            async with client:
                resp = await client.post("/upload/aibot", data=_upload(payload))
                assert resp.status == 200
                data = await resp.json()
                assert data["cached"] is True
                assert data["file_id"] is None
        finally:
            reg.close()
            tmp.cleanup()

    async def test_concurrent_uploads_same_content(
        self, reg_and_storage: tuple[UploadRegistry, MagicMock, TemporaryDirectory[str]]
    ) -> None:
        reg, storage, tmp = reg_and_storage
        try:
            app = _make_app(
                registry=reg,
                storage=storage,
                client_map={"aibot": MagicMock()},
            )
            client = TestClient(TestServer(app))
            async with client:
                payload = b"concurrent data"
                resp1 = await client.post("/upload/aibot", data=_upload(payload))
                resp2 = await client.post("/upload/aibot", data=_upload(payload))
                data1 = await resp1.json()
                data2 = await resp2.json()
                assert data1["upload_id"] == data2["upload_id"]
        finally:
            reg.close()
            tmp.cleanup()
