from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.broker.consumer import Consumer


@pytest.fixture
def mock_manager() -> MagicMock:
    m = MagicMock()
    m.connection = AsyncMock()
    m.connection.is_closed = False
    return m


class TestConsumer:
    async def test_start_with_routing_key_binds_exchange(
        self, mock_manager: MagicMock
    ) -> None:
        consumer = Consumer(
            mock_manager,
            "test-queue",
            AsyncMock(),
            routing_key="test-key",
        )
        channel = AsyncMock()
        mock_manager.connection.channel.return_value = channel
        queue = AsyncMock()
        channel.declare_queue.return_value = queue
        exchange = AsyncMock()
        channel.get_exchange.return_value = exchange

        await consumer.start()

        channel.get_exchange.assert_awaited_once_with("tg-if.responses")
        queue.bind.assert_awaited_once_with(exchange, routing_key="test-key")
        await consumer.stop()

    async def test_start_without_routing_key_skips_bind(
        self, mock_manager: MagicMock
    ) -> None:
        consumer = Consumer(
            mock_manager,
            "test-queue",
            AsyncMock(),
        )
        channel = AsyncMock()
        mock_manager.connection.channel.return_value = channel
        queue = AsyncMock()
        channel.declare_queue.return_value = queue

        await consumer.start()

        channel.get_exchange.assert_not_awaited()
        queue.bind.assert_not_awaited()
        await consumer.stop()

    async def test_start_raises_error_when_not_connected(
        self, mock_manager: MagicMock
    ) -> None:
        mock_manager.connection = None
        consumer = Consumer(
            mock_manager,
            "test-queue",
            AsyncMock(),
            routing_key="test-key",
        )
        with pytest.raises(Exception, match="not connected"):
            await consumer.start()

    async def test_stop_sets_task_to_none(self, mock_manager: MagicMock) -> None:
        consumer = Consumer(
            mock_manager,
            "test-queue",
            AsyncMock(),
            routing_key="test-key",
        )
        channel = AsyncMock()
        mock_manager.connection.channel.return_value = channel
        queue = AsyncMock()
        channel.declare_queue.return_value = queue
        exchange = AsyncMock()
        channel.get_exchange.return_value = exchange

        await consumer.start()
        assert consumer._task is not None
        await consumer.stop()
        assert consumer._task is None
