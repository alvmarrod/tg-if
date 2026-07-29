import json
from collections.abc import Mapping
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
        self, routing_key: str, message: Mapping[str, Any] | BaseModel
    ) -> bool:
        """Publish a message to the specified routing key.

        Args:
            routing_key: The routing key to publish to
            message: The message to publish (dict or BaseModel)

        Returns:
            True if message was published successfully

        Raises:
            PublisherError: If routing_key is empty, not connected, or connection is closed
        """
        if not routing_key:
            raise PublisherError("routing_key cannot be empty")

        conn = self._manager.connection
        if conn is None:
            raise PublisherError("not connected to broker")
        if conn.is_closed:
            raise PublisherError("broker connection is closed")

        if isinstance(message, BaseModel):
            body = message.model_dump_json().encode()
        elif isinstance(message, Mapping):
            body = json.dumps(message).encode()
        else:
            raise PublisherError(
                f"unsupported message type: {type(message).__name__}, "
                f"expected dict or BaseModel"
            )

        try:
            async with await conn.channel() as channel:
                exchange = await channel.declare_exchange(
                    "tg-if.events", aio_pika.ExchangeType.TOPIC, durable=True
                )

                msg: aio_pika.Message = aio_pika.Message(
                    body=body, delivery_mode=DeliveryMode.PERSISTENT
                )
                await exchange.publish(msg, routing_key=routing_key)
                return True
        except aio_pika.exceptions.AMQPError as e:
            raise PublisherError(f"failed to publish message to {routing_key}: {e}")
