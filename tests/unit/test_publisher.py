from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, Field

from infrastructure.broker.publisher import Publisher, PublisherError
from infrastructure.broker.rabbitmq import RabbitMQManager
from infrastructure.config import BrokerConfig


class _TestModel(BaseModel):
    name: str = Field(default="test")


@pytest.fixture
def manager() -> RabbitMQManager:
    cfg = BrokerConfig(
        host="localhost", port=5672, user="guest", password="guest", vhost="/"
    )
    return RabbitMQManager(cfg)


@pytest.fixture
def publisher(manager: RabbitMQManager) -> Publisher:
    return Publisher(manager)


@pytest.fixture
def mock_conn() -> AsyncMock:
    conn = AsyncMock()
    conn.is_closed = False
    ch = AsyncMock()
    ch.is_closed = False
    ch.declare_exchange = AsyncMock()
    conn.channel = AsyncMock(return_value=ch)
    return conn


class TestEnsureChannel:
    async def test_channel_already_open(self, publisher: Publisher) -> None:
        mock_ch = AsyncMock()
        mock_ch.is_closed = False
        publisher._channel = mock_ch
        await publisher._ensure_channel()
        mock_ch.channel.assert_not_called()

    async def test_no_connection(self, publisher: Publisher) -> None:
        publisher._channel = None
        publisher._manager._connection = None
        with pytest.raises(PublisherError, match="not connected"):
            await publisher._ensure_channel()

    async def test_connection_closed(self, publisher: Publisher) -> None:
        publisher._channel = None
        mock_conn = MagicMock()
        mock_conn.is_closed = True
        publisher._manager._connection = mock_conn
        with pytest.raises(PublisherError, match="connection is closed"):
            await publisher._ensure_channel()

    async def test_opens_channel(
        self, publisher: Publisher, mock_conn: AsyncMock
    ) -> None:
        publisher._channel = None
        publisher._manager._connection = mock_conn
        await publisher._ensure_channel()
        mock_conn.channel.assert_awaited_once()
        ch = mock_conn.channel.return_value
        ch.declare_exchange.assert_awaited_once()
        assert publisher._channel is ch


class TestClose:
    async def test_no_channel(self, publisher: Publisher) -> None:
        publisher._channel = None
        await publisher.close()
        assert publisher._channel is None
        assert publisher._exchange is None

    async def test_channel_already_closed(self, publisher: Publisher) -> None:
        mock_ch = AsyncMock()
        mock_ch.is_closed = True
        publisher._channel = mock_ch
        await publisher.close()
        assert publisher._channel is None

    async def test_closes_open_channel(self, publisher: Publisher) -> None:
        mock_ch = AsyncMock()
        mock_ch.is_closed = False
        mock_ch.close = AsyncMock()
        publisher._channel = mock_ch
        publisher._exchange = MagicMock()
        await publisher.close()
        mock_ch.close.assert_awaited_once()
        assert publisher._channel is None
        assert publisher._exchange is None


class TestPublishValidation:
    async def test_empty_routing_key(self, publisher: Publisher) -> None:
        with pytest.raises(PublisherError, match="routing_key cannot be empty"):
            await publisher.publish("", {"data": 1})

    async def test_unsupported_message_type(self, publisher: Publisher) -> None:
        with pytest.raises(PublisherError, match="unsupported message type"):
            await publisher.publish("test.rk", "plain string")  # type: ignore[arg-type]

    async def test_base_model_serialization(
        self, publisher: Publisher, mock_conn: AsyncMock
    ) -> None:
        publisher._manager._connection = mock_conn
        publisher._channel = mock_conn.channel.return_value
        publisher._exchange = (
            mock_conn.channel.return_value.declare_exchange.return_value
        )

        msg = _TestModel(name="hello")
        result = await publisher.publish("incoming.events.testbot.msg.text", msg)
        assert result is True
        call_args = publisher._exchange.publish.await_args
        body = json.loads(call_args.args[0].body)
        assert body["name"] == "hello"

    async def test_dict_serialization(
        self, publisher: Publisher, mock_conn: AsyncMock
    ) -> None:
        publisher._manager._connection = mock_conn
        publisher._channel = mock_conn.channel.return_value
        publisher._exchange = (
            mock_conn.channel.return_value.declare_exchange.return_value
        )

        result = await publisher.publish(
            "test.events.foo.bar", {"key": "val", "num": 42}
        )
        assert result is True
        call_args = publisher._exchange.publish.await_args
        body = json.loads(call_args.args[0].body)
        assert body == {"key": "val", "num": 42}

    async def test_amqp_error_converts(
        self, publisher: Publisher, mock_conn: AsyncMock
    ) -> None:
        import aio_pika

        publisher._manager._connection = mock_conn
        publisher._channel = mock_conn.channel.return_value
        mock_ex = AsyncMock()
        mock_ex.publish.side_effect = aio_pika.exceptions.AMQPError("channel down")
        publisher._exchange = mock_ex

        with pytest.raises(PublisherError, match="failed to publish message"):
            await publisher.publish("test.rk", {"x": 1})
