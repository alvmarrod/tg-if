import json
from typing import Any

import aio_pika
from aio_pika import DeliveryMode
from pydantic import BaseModel

from infrastructure.broker.rabbitmq import RabbitMQManager


class PublisherError(Exception):
    pass


class Publisher:
    def __init__(self, manager: RabbitMQManager) -> None:
        self._manager = manager

    async def publish(
        self, routing_key: str, message: dict[str, Any] | BaseModel
    ) -> None:
        conn = self._manager.connection
        if not conn or conn.is_closed:
            raise PublisherError("not connected to broker")

        if isinstance(message, BaseModel):
            body = message.model_dump_json().encode()
        else:
            body = json.dumps(message).encode()

        async with conn.channel() as channel:
            exchange = await channel.get_exchange("tg-if.events")
            msg = aio_pika.Message(body=body, delivery_mode=DeliveryMode.PERSISTENT)
            await exchange.publish(msg, routing_key=routing_key)
