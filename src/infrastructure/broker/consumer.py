import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
import structlog
from aio_pika import DeliveryMode
from aio_pika.abc import AbstractChannel, AbstractQueue

from infrastructure.broker.rabbitmq import RabbitMQManager


logger = structlog.get_logger()

OnFailedCallback = Callable[[dict[str, Any], Exception], Awaitable[Any]]


class ConsumerError(Exception):
    pass


class Consumer:
    def __init__(
        self,
        manager: RabbitMQManager,
        queue_name: str,
        callback: Callable[[dict[str, Any]], Awaitable[Any]],
        max_retries: int = 3,
        on_failed: OnFailedCallback | None = None,
        routing_key: str | None = None,
    ) -> None:
        self._manager = manager
        self._queue_name = queue_name
        self._callback = callback
        self._max_retries = max_retries
        self._on_failed = on_failed
        self._routing_key = routing_key
        self._channel: AbstractChannel | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        conn = self._manager.connection
        if conn is None:
            raise ConsumerError("not connected to broker")
        if conn.is_closed:
            raise ConsumerError("broker connection is closed")

        self._channel = await conn.channel()
        queue = await self._channel.declare_queue(self._queue_name, durable=True)

        if self._routing_key is not None:
            exchange = await self._channel.get_exchange("tg-if.responses")
            await queue.bind(exchange, routing_key=self._routing_key)

        self._task = asyncio.create_task(self._run(queue))

    async def _run(self, queue: AbstractQueue) -> None:
        try:
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process():
                        try:
                            body: dict[str, Any] = json.loads(message.body.decode())
                        except json.JSONDecodeError:
                            logger.exception(
                                "invalid message body", queue=self._queue_name
                            )
                            continue

                        await self._call_with_retry(body)
        except asyncio.CancelledError:
            pass

    async def _call_with_retry(self, body: dict[str, Any]) -> None:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                await self._callback(body)
                return
            except Exception as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    delay = min(attempt + 1, 5)
                    logger.warning(
                        "consumer callback failed, retrying",
                        queue=self._queue_name,
                        attempt=attempt + 1,
                        max_retries=self._max_retries,
                        delay=delay,
                    )
                    await asyncio.sleep(delay)

        logger.error(
            "consumer callback failed after all retries",
            queue=self._queue_name,
            max_retries=self._max_retries,
        )
        if self._on_failed and last_exc is not None:
            try:
                await self._on_failed(body, last_exc)
            except Exception:
                logger.exception("on_failed callback failed", queue=self._queue_name)

        await self._publish_dead_letter(body, last_exc)

    async def _publish_dead_letter(
        self, body: dict[str, Any], exc: Exception | None
    ) -> None:
        if self._channel is None or self._channel.is_closed:
            logger.warning("cannot publish dead-letter: channel not available")
            return
        try:
            exchange = await self._channel.get_exchange("tg-if.dlq")
            dlq_body = {
                "original": body,
                "error": str(exc) if exc else "unknown",
                "queue": self._queue_name,
            }
            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(dlq_body).encode(),
                    delivery_mode=DeliveryMode.PERSISTENT,
                ),
                routing_key="dlq",
            )
        except Exception:
            logger.exception("failed to publish dead-letter message")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._channel is not None and not self._channel.is_closed:
            await self._channel.close()
