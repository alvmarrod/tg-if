import structlog
from typing import Any
from aio_pika import connect_robust
from aio_pika import ExchangeType
from aio_pika.abc import AbstractRobustConnection

from infrastructure.config import BrokerConfig


logger = structlog.get_logger()


class RabbitMQManager:
    def __init__(self, config: BrokerConfig) -> None:
        self._config = config
        self._connection: AbstractRobustConnection | None = None
        self._channel: Any | None = None

    def _amqp_url(self) -> str:
        if self._config.user is None:
            raise ValueError("broker config requires user")
        if self._config.password is None:
            raise ValueError("broker config requires password")
        if self._config.host is None:
            raise ValueError("broker config requires host")
        if self._config.port is None:
            raise ValueError("broker config requires port")
        if self._config.vhost is None:
            raise ValueError("broker config requires vhost")
        return (
            f"amqp://{self._config.user}:{self._config.password}"
            f"@{self._config.host}:{self._config.port}"
            f"{self._config.vhost}"
        )

    async def connect(self) -> None:
        try:
            self._connection = await connect_robust(self._amqp_url())
            self._channel = await self._connection.channel()
            await self._channel.declare_exchange(
                "tg-if.events",
                type=ExchangeType.TOPIC,
                durable=True,
            )
            await self._channel.declare_exchange(
                "tg-if.responses",
                type=ExchangeType.DIRECT,
                durable=True,
            )
            await self._channel.declare_exchange(
                "tg-if.dlq",
                type=ExchangeType.DIRECT,
                durable=True,
            )
            await self._channel.declare_queue("dead-letter", durable=True)
            dlq_exchange = await self._channel.get_exchange("tg-if.dlq")
            dlq_queue = await self._channel.get_queue("dead-letter")
            await dlq_queue.bind(dlq_exchange, routing_key="dlq")
            await self._channel.declare_queue("outgoing.responses", durable=True)
            await self._channel.declare_queue("media-config", durable=True)
            await self._channel.declare_queue("subscriber-commands", durable=True)
            logger.info(
                "broker connected", host=self._config.host, vhost=self._config.vhost
            )
        except Exception:
            logger.warning(
                "broker connection failed", host=self._config.host, exc_info=True
            )
            raise

    async def disconnect(self) -> None:
        if self._connection is not None:
            try:
                if self._channel is not None:
                    if hasattr(self._channel, "close"):
                        await self._channel.close()
                await self._connection.close()
                logger.info("broker disconnected")
            except Exception:
                logger.warning("broker disconnect failed", exc_info=True)
                raise
            finally:
                self._connection = None
                self._channel = None

    async def health(self) -> bool:
        if self._connection is None:
            return False
        # Ensure connection is not closed
        return not self._connection.is_closed

    @property
    def connection(self) -> AbstractRobustConnection | None:
        return self._connection
