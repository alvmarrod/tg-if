import asyncio
import json
from collections.abc import Callable
from typing import Any

import structlog
from aio_pika.abc import AbstractChannel

from infrastructure.broker.rabbitmq import RabbitMQManager


logger = structlog.get_logger()


class ConsumerError(Exception):
    pass


class Consumer:
    def __init__(
        self,
        manager: RabbitMQManager,
        queue_name: str,
        callback: Callable[[dict[str, Any]], Any],
    ) -> None:
        self._manager = manager
        self._queue_name = queue_name
        self._callback = callback
        self._channel: AbstractChannel | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        conn = self._manager.connection
        if not conn or conn.is_closed:
            raise ConsumerError("not connected to broker")

        self._channel = await conn.channel()
        assert self._channel is not None
        queue = await self._channel.declare_queue(self._queue_name, durable=True)

        if self._queue_name == "outgoing.responses":
            exchange = await self._channel.get_exchange("tg-if.responses")
            await queue.bind(exchange, routing_key="response")

        self._task = asyncio.create_task(self._run(queue))

    async def _run(self, queue: Any) -> None:
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    try:
                        body: dict[str, Any] = json.loads(message.body.decode())
                        await self._callback(body)
                    except Exception:
                        logger.exception(
                            "consumer callback failed", queue=self._queue_name
                        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._channel is not None and not self._channel.is_closed:
            await self._channel.close()
