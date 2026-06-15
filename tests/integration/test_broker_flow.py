from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from infrastructure.broker import Consumer, Publisher, RabbitMQManager
from infrastructure.config import BrokerConfig


pytestmark = pytest.mark.integration


@pytest.fixture
async def manager(
    rabbitmq_config: BrokerConfig,
) -> AsyncGenerator[RabbitMQManager, None]:
    m = RabbitMQManager(rabbitmq_config)
    await m.connect()
    yield m
    await m.disconnect()


class TestBrokerFlow:
    async def test_publish_and_consume(self, manager: RabbitMQManager) -> None:
        received: list[dict[str, Any]] = []
        event = asyncio.Event()

        async def callback(body: dict[str, Any]) -> None:
            received.append(body)
            event.set()

        conn = manager.connection
        assert conn is not None and not conn.is_closed

        ch = await conn.channel()
        queue = await ch.declare_queue("test-publish-consume", durable=True)
        exchange = await ch.get_exchange("tg-if.events")
        await queue.bind(exchange, routing_key="test.publish.consume")
        await ch.close()

        consumer = Consumer(manager, "test-publish-consume", callback)
        await consumer.start()

        publisher = Publisher(manager)
        payload = {"msg": "hello", "n": 42}
        await publisher.publish("test.publish.consume", payload)

        await asyncio.wait_for(event.wait(), timeout=10)
        await consumer.stop()

        assert len(received) == 1
        assert received[0]["msg"] == "hello"
        assert received[0]["n"] == 42

    async def test_consumer_retry_round_trip(self, manager: RabbitMQManager) -> None:
        call_count = 0
        event = asyncio.Event()

        async def callback(body: dict[str, Any]) -> None:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError(f"attempt {call_count} failed")
            event.set()

        conn = manager.connection
        assert conn is not None and not conn.is_closed

        ch = await conn.channel()
        queue = await ch.declare_queue("test-retry-round-trip", durable=True)
        exchange = await ch.get_exchange("tg-if.events")
        await queue.bind(exchange, routing_key="test.retry.round.trip")
        await ch.close()

        consumer = Consumer(manager, "test-retry-round-trip", callback, max_retries=3)
        await consumer.start()

        publisher = Publisher(manager)
        await publisher.publish("test.retry.round.trip", {"status": "retry-me"})

        await asyncio.wait_for(event.wait(), timeout=10)
        await consumer.stop()

        assert call_count == 3
