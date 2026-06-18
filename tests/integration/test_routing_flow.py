from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import aio_pika
import pytest
from aio_pika import DeliveryMode

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


class TestTopicRouting:
    async def test_wildcard_matches_subtopic(self, manager: RabbitMQManager) -> None:
        received: list[dict[str, Any]] = []
        event = asyncio.Event()

        async def callback(body: dict[str, Any]) -> None:
            received.append(body)
            event.set()

        conn = manager.connection
        assert conn is not None and not conn.is_closed

        ch = await conn.channel()
        queue = await ch.declare_queue("test-wildcard-match", durable=True)
        exchange = await ch.get_exchange("tg-if.events")
        await queue.bind(exchange, routing_key="incoming.events.aibot.#")
        await ch.close()

        consumer = Consumer(manager, "test-wildcard-match", callback)
        await consumer.start()

        publisher = Publisher(manager)
        await publisher.publish("incoming.events.aibot.messages.text", {"text": "hi"})

        await asyncio.wait_for(event.wait(), timeout=10)
        await consumer.stop()

        assert len(received) == 1
        assert received[0]["text"] == "hi"

    async def test_wildcard_filters_other_bot(self, manager: RabbitMQManager) -> None:
        received: list[dict[str, Any]] = []
        event = asyncio.Event()

        async def callback(body: dict[str, Any]) -> None:
            received.append(body)
            event.set()

        conn = manager.connection
        assert conn is not None and not conn.is_closed

        ch = await conn.channel()
        queue = await ch.declare_queue("test-wildcard-filter", durable=True)
        exchange = await ch.get_exchange("tg-if.events")
        await queue.bind(exchange, routing_key="incoming.events.aibot.#")
        await ch.close()

        consumer = Consumer(manager, "test-wildcard-filter", callback)
        await consumer.start()

        publisher = Publisher(manager)
        await publisher.publish(
            "incoming.events.supportbot.messages.text", {"text": "nope"}
        )

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=2)
        await consumer.stop()

        assert len(received) == 0

    async def test_fan_out_delivers_to_all_subscribers(
        self,
        manager: RabbitMQManager,
    ) -> None:
        received_a: list[dict[str, Any]] = []
        received_b: list[dict[str, Any]] = []
        event_a = asyncio.Event()
        event_b = asyncio.Event()

        async def callback_a(body: dict[str, Any]) -> None:
            received_a.append(body)
            event_a.set()

        async def callback_b(body: dict[str, Any]) -> None:
            received_b.append(body)
            event_b.set()

        conn = manager.connection
        assert conn is not None and not conn.is_closed

        ch = await conn.channel()
        exchange = await ch.get_exchange("tg-if.events")

        qa = await ch.declare_queue("test-fanout-a", durable=True)
        await qa.bind(exchange, routing_key="incoming.events.aibot.#")

        qb = await ch.declare_queue("test-fanout-b", durable=True)
        await qb.bind(exchange, routing_key="incoming.events.aibot.#")
        await ch.close()

        ca = Consumer(manager, "test-fanout-a", callback_a)
        cb = Consumer(manager, "test-fanout-b", callback_b)
        await ca.start()
        await cb.start()

        publisher = Publisher(manager)
        await publisher.publish("incoming.events.aibot.messages.text", {"msg": "fan"})

        await asyncio.wait_for(event_a.wait(), timeout=10)
        await asyncio.wait_for(event_b.wait(), timeout=10)
        await ca.stop()
        await cb.stop()

        assert len(received_a) == 1
        assert len(received_b) == 1
        assert received_a[0]["msg"] == "fan"
        assert received_b[0]["msg"] == "fan"


class TestMediaConfigConsumer:
    async def test_consumes_media_config_message(
        self,
        manager: RabbitMQManager,
    ) -> None:
        received: list[dict[str, Any]] = []
        event = asyncio.Event()

        async def callback(body: dict[str, Any]) -> None:
            received.append(body)
            event.set()

        consumer = Consumer(
            manager, "media-config", callback, routing_key="media-config"
        )
        await consumer.start()

        conn = manager.connection
        assert conn is not None and not conn.is_closed

        payload = {
            "scope": "global",
            "action": "eager",
            "content_types": ["all"],
        }

        async with conn.channel() as channel:
            exchange = await channel.get_exchange("tg-if.responses")
            msg = aio_pika.Message(
                body=json.dumps(payload).encode(),
                delivery_mode=DeliveryMode.PERSISTENT,
            )
            await exchange.publish(msg, routing_key="media-config")

        await asyncio.wait_for(event.wait(), timeout=10)
        await consumer.stop()

        assert len(received) == 1
        assert received[0]["scope"] == "global"
        assert received[0]["action"] == "eager"


class TestSubscriberCommands:
    async def test_register_command_via_subscriber_commands_queue(
        self,
        manager: RabbitMQManager,
    ) -> None:
        received: list[dict[str, Any]] = []
        event = asyncio.Event()

        async def callback(body: dict[str, Any]) -> None:
            received.append(body)
            event.set()

        consumer = Consumer(
            manager,
            "subscriber-commands",
            callback,
            routing_key="subscriber-commands",
        )
        await consumer.start()

        conn = manager.connection
        assert conn is not None and not conn.is_closed

        payload = {
            "action": "register",
            "bot_id": "aibot",
            "subscriber_id": "svc_1",
            "commands": [{"command": "start", "description": "Start"}],
        }

        async with conn.channel() as channel:
            exchange = await channel.get_exchange("tg-if.responses")
            msg = aio_pika.Message(
                body=json.dumps(payload).encode(),
                delivery_mode=DeliveryMode.PERSISTENT,
            )
            await exchange.publish(msg, routing_key="subscriber-commands")

        await asyncio.wait_for(event.wait(), timeout=10)
        await consumer.stop()

        assert len(received) == 1
        assert received[0]["action"] == "register"
        assert received[0]["bot_id"] == "aibot"
        assert received[0]["commands"][0]["command"] == "start"
