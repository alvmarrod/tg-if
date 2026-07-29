from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.config import BrokerConfig
from infrastructure.broker.rabbitmq import RabbitMQManager


@pytest.fixture
def valid_config() -> BrokerConfig:
    return BrokerConfig(
        host="localhost",
        port=5672,
        user="guest",
        password="guest",
        vhost="/",
    )


@pytest.fixture
def manager(valid_config: BrokerConfig) -> RabbitMQManager:
    return RabbitMQManager(valid_config)


class TestAmqpUrl:
    def test_builds_valid_url(self, manager: RabbitMQManager) -> None:
        url = manager._amqp_url()
        assert url == "amqp://guest:guest@localhost:5672/"

    def test_default_vhost_slash(self, valid_config: BrokerConfig) -> None:
        m = RabbitMQManager(valid_config)
        assert "/" in m._amqp_url()

    def test_requires_user(self, manager: RabbitMQManager) -> None:
        manager._config.user = None  # type: ignore[assignment]
        with pytest.raises(ValueError, match="user"):
            manager._amqp_url()

    def test_requires_password(self, manager: RabbitMQManager) -> None:
        manager._config.password = None  # type: ignore[assignment]
        with pytest.raises(ValueError, match="password"):
            manager._amqp_url()

    def test_requires_host(self, manager: RabbitMQManager) -> None:
        manager._config.host = None  # type: ignore[assignment]
        with pytest.raises(ValueError, match="host"):
            manager._amqp_url()

    def test_requires_port(self, manager: RabbitMQManager) -> None:
        manager._config.port = None  # type: ignore[assignment]
        with pytest.raises(ValueError, match="port"):
            manager._amqp_url()

    def test_requires_vhost(self, manager: RabbitMQManager) -> None:
        manager._config.vhost = None  # type: ignore[assignment]
        with pytest.raises(ValueError, match="vhost"):
            manager._amqp_url()


class TestHealth:
    async def test_no_connection_returns_false(self, manager: RabbitMQManager) -> None:
        assert manager._connection is None
        assert await manager.health() is False

    async def test_connection_open_returns_true(self, manager: RabbitMQManager) -> None:
        mock_conn = MagicMock()
        mock_conn.is_closed = False
        manager._connection = mock_conn
        assert await manager.health() is True

    async def test_connection_closed_returns_false(
        self, manager: RabbitMQManager
    ) -> None:
        mock_conn = MagicMock()
        mock_conn.is_closed = True
        manager._connection = mock_conn
        assert await manager.health() is False


class TestConnectionProperty:
    def test_returns_none_initially(self, manager: RabbitMQManager) -> None:
        assert manager.connection is None

    def test_returns_connection_after_set(self, manager: RabbitMQManager) -> None:
        mock_conn = MagicMock()
        manager._connection = mock_conn
        assert manager.connection is mock_conn


class TestDisconnect:
    async def test_no_connection_is_noop(self, manager: RabbitMQManager) -> None:
        await manager.disconnect()

    async def test_connection_no_channel(self, manager: RabbitMQManager) -> None:
        mock_conn = AsyncMock()
        mock_conn.close = AsyncMock()
        manager._connection = mock_conn
        manager._channel = None
        await manager.disconnect()
        mock_conn.close.assert_awaited_once()
        assert manager._connection is None

    async def test_connection_with_channel(self, manager: RabbitMQManager) -> None:
        mock_conn = AsyncMock()
        mock_conn.close = AsyncMock()
        mock_channel = MagicMock()
        mock_channel.close = AsyncMock()
        manager._connection = mock_conn
        manager._channel = mock_channel
        await manager.disconnect()
        mock_channel.close.assert_awaited_once()
        mock_conn.close.assert_awaited_once()
        assert manager._connection is None
        assert manager._channel is None

    async def test_channel_without_close_method(self, manager: RabbitMQManager) -> None:
        mock_conn = AsyncMock()
        mock_conn.close = AsyncMock()
        mock_channel = MagicMock(spec=[])  # no close attr
        manager._connection = mock_conn
        manager._channel = mock_channel
        await manager.disconnect()
        mock_conn.close.assert_awaited_once()
        assert manager._connection is None

    async def test_close_failure(self, manager: RabbitMQManager) -> None:
        mock_conn = AsyncMock()
        mock_conn.close = AsyncMock(side_effect=ConnectionError("gone"))
        manager._connection = mock_conn
        manager._channel = None
        with pytest.raises(ConnectionError):
            await manager.disconnect()
        assert manager._connection is None


class TestConnect:
    async def test_connect_success(
        self, manager: RabbitMQManager, valid_config: BrokerConfig
    ) -> None:
        mock_conn = AsyncMock()
        mock_channel = AsyncMock()
        mock_channel.declare_exchange = AsyncMock()
        mock_channel.declare_queue = AsyncMock()
        mock_channel.get_exchange = AsyncMock()
        mock_channel.get_queue = AsyncMock()
        mock_conn.channel = AsyncMock(return_value=mock_channel)

        mock_dlq_exchange = AsyncMock()
        mock_dlq_queue = AsyncMock()
        mock_dlq_queue.bind = AsyncMock()
        mock_channel.get_exchange.side_effect = lambda name: {
            "tg-if.dlq": mock_dlq_exchange,
        }.get(name, AsyncMock())
        mock_channel.get_queue.side_effect = lambda name: {
            "dead-letter": mock_dlq_queue,
        }.get(name, AsyncMock())

        with patch(
            "infrastructure.broker.rabbitmq.connect_robust",
            return_value=mock_conn,
        ):
            await manager.connect()

        mock_conn.channel.assert_awaited_once()
        assert mock_channel.declare_exchange.await_count == 3
        assert mock_channel.declare_queue.await_count == 4

    async def test_connect_failure(
        self, manager: RabbitMQManager, valid_config: BrokerConfig
    ) -> None:
        with (
            patch(
                "infrastructure.broker.rabbitmq.connect_robust",
                side_effect=ConnectionError("host unreachable"),
            ),
            pytest.raises(ConnectionError),
        ):
            await manager.connect()
