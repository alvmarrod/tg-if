from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer
from aio_pika import DeliveryMode, Message

from app.response_consumer import ResponseConsumer
from domain.schemas import UploadEntry
from infrastructure.broker import Consumer, RabbitMQManager
from infrastructure.config import BrokerConfig
from infrastructure.media.storage import DiskStorage
from infrastructure.media.upload_routes import (
    ClientMapKey,
    MaxUploadSizeKey,
    MediaStorageKey,
    UploadRegistryKey,
    handle_upload_post,
)
from infrastructure.sqlite import UploadRegistry


pytestmark = pytest.mark.integration


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


def _photo_result(
    file_id: str = "AgAC_test", file_unique_id: str = "QQAD_test"
) -> MagicMock:
    result: MagicMock = MagicMock(spec=[])
    photo_attr: MagicMock = MagicMock(spec=[])
    photo_attr.file_id = file_id
    photo_attr.file_unique_id = file_unique_id
    result.photo = photo_attr
    return result


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_upload_app(
    registry: UploadRegistry,
    storage: DiskStorage,
    clients: dict[str, Any],
) -> web.Application:
    app = web.Application()
    app[UploadRegistryKey] = registry
    app[MediaStorageKey] = storage
    app[ClientMapKey] = clients
    app[MaxUploadSizeKey] = 2000 * 1024 * 1024
    app.router.add_post("/upload/{bot_id}", handle_upload_post)
    return app


@pytest.fixture
async def manager(
    rabbitmq_config: BrokerConfig,
) -> AsyncGenerator[RabbitMQManager, None]:
    m = RabbitMQManager(rabbitmq_config)
    await m.connect()
    yield m
    await m.disconnect()


@pytest.fixture
async def reg_storage() -> AsyncGenerator[tuple[UploadRegistry, DiskStorage], None]:
    tmp = TemporaryDirectory()
    db_path = str(Path(tmp.name) / "uploads.db")
    reg = UploadRegistry(db_path)
    reg.connect()
    storage = DiskStorage(tmp.name)
    try:
        yield reg, storage
    finally:
        reg.close()
        tmp.cleanup()


class TestUploadIntegration:
    async def test_upload_to_amqp_round_trip(
        self,
        manager: RabbitMQManager,
        reg_storage: tuple[UploadRegistry, DiskStorage],
    ) -> None:
        reg, storage = reg_storage
        done = asyncio.Event()

        clients: dict[str, Any] = {"aibot": MockClient("aibot")}
        clients["aibot"].send_photo.side_effect = _make_send_photo(done)

        consumer = ResponseConsumer(
            clients, manager, registry=reg, upload_storage=storage
        )
        amqp = Consumer(
            manager, "outgoing.responses", consumer.handle, routing_key="response"
        )
        await amqp.start()

        app = _make_upload_app(reg, storage, clients)

        try:
            async with TestClient(TestServer(app)) as client:
                fd = FormData()
                fd.add_field("file", b"integration upload content", filename="img.jpg")
                resp = await client.post("/upload/aibot", data=fd)
                assert resp.status == 200
                data = await resp.json()
                assert data["upload_id"].startswith("upl_")
                assert data["cached"] is False
                assert data["ext"] == "jpg"
                upload_id = data["upload_id"]

            body: dict[str, Any] = {
                "response_id": "int_rt_1",
                "correlation_id": "int_rt_1",
                "timestamp": "2025-01-01T00:00:00",
                "bot_id": "aibot",
                "chat_id": 12345,
                "response_type": "photo",
                "payload": {"photo": upload_id, "caption": "roundtrip"},
            }

            conn = manager.connection
            assert conn is not None
            async with conn.channel() as channel:
                exchange = await channel.get_exchange("tg-if.responses")
                await exchange.publish(
                    Message(
                        body=json.dumps(body).encode(),
                        delivery_mode=DeliveryMode.PERSISTENT,
                    ),
                    routing_key="response",
                )

            await asyncio.wait_for(done.wait(), timeout=10)

            clients["aibot"].send_photo.assert_awaited_once()
            assert clients["aibot"].send_photo.await_args is not None
            kwargs = clients["aibot"].send_photo.await_args.kwargs
            assert kwargs["chat_id"] == 12345
            assert kwargs["caption"] == "roundtrip"
            # Slow path: resolved to a filesystem path (no file_id cached yet)
            assert isinstance(kwargs["photo"], str)
            assert not kwargs["photo"].startswith("upl_")

            # After send, file_id was extracted and registry updated
            content_hash = upload_id[4:]
            entry = reg.get_by_hash(content_hash)
            assert entry is not None
            assert entry.file_id == "AgAC_test"
            assert entry.file_unique_id == "QQAD_test"
        finally:
            await amqp.stop()

    async def test_fast_path_existing_file_id(
        self,
        manager: RabbitMQManager,
        reg_storage: tuple[UploadRegistry, DiskStorage],
    ) -> None:
        reg, storage = reg_storage
        done = asyncio.Event()

        clients: dict[str, Any] = {"aibot": MockClient("aibot")}
        clients["aibot"].send_photo.side_effect = _make_send_photo(done)

        content_hash = "pretend_fast_hash"
        reg.register(
            UploadEntry(
                content_hash=content_hash,
                bot_id="aibot",
                ext="jpg",
                size=456,
            )
        )
        reg.update_file_id(content_hash, "AgAC_pre_existing", "QQAD_pre_existing")

        consumer = ResponseConsumer(
            clients, manager, registry=reg, upload_storage=storage
        )
        amqp = Consumer(
            manager, "outgoing.responses", consumer.handle, routing_key="response"
        )
        await amqp.start()

        try:
            body: dict[str, Any] = {
                "response_id": "int_fast_1",
                "correlation_id": "int_fast_1",
                "timestamp": "2025-01-01T00:00:00",
                "bot_id": "aibot",
                "chat_id": 12345,
                "response_type": "photo",
                "payload": {
                    "photo": f"upl_{content_hash}",
                    "caption": "fast path",
                },
            }

            conn = manager.connection
            assert conn is not None
            async with conn.channel() as channel:
                exchange = await channel.get_exchange("tg-if.responses")
                await exchange.publish(
                    Message(
                        body=json.dumps(body).encode(),
                        delivery_mode=DeliveryMode.PERSISTENT,
                    ),
                    routing_key="response",
                )

            await asyncio.wait_for(done.wait(), timeout=10)

            clients["aibot"].send_photo.assert_awaited_once_with(
                chat_id=12345,
                photo="AgAC_pre_existing",
                caption="fast path",
            )
        finally:
            await amqp.stop()


def _make_send_photo(done: asyncio.Event) -> Any:
    async def send_photo(**kw: Any) -> MagicMock:
        done.set()
        return _photo_result()

    return send_photo
