import structlog
from aio_pika import connect_robust
from aio_pika import ExchangeType
from aio_pika.abc import AbstractRobustConnection

from infrastructure.config import BrokerConfig


logger = structlog.get_logger()


class RabbitMQManager:
    def __init__(self, config: BrokerConfig) -> None:
        self._config = config
        self._connection: AbstractRobustConnection | None = None

    def _amqp_url(self) -> str:
        return (
            f"amqp://{self._config.user}:{self._config.password}"
            f"@{self._config.host}:{self._config.port}"
            f"{self._config.vhost}"
        )

    async def connect(self) -> None:
        try:
            self._connection = await connect_robust(self._amqp_url())
            channel = await self._connection.channel()
            await channel.declare_exchange(
                "tg-if.events",
                type=ExchangeType.TOPIC,
                durable=True,
            )
            await channel.declare_exchange(
                "tg-if.responses",
                type=ExchangeType.DIRECT,
                durable=True,
            )
            await channel.declare_queue("outgoing.responses", durable=True)
            await channel.declare_queue("media-config", durable=True)
            await channel.declare_queue("subscriber-commands", durable=True)
            await channel.close()
            logger.info(
                "broker connected", host=self._config.host, vhost=self._config.vhost
            )
        except Exception:
            logger.warning(
                "broker connection failed", host=self._config.host, exc_info=True
            )

    async def disconnect(self) -> None:
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
            logger.info("broker disconnected")

    async def health(self) -> bool:
        if not self._connection:
            return False
        return not self._connection.is_closed

    @property
    def connection(self) -> AbstractRobustConnection | None:
        return self._connection
