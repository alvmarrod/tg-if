from typing import Any

import structlog

from app.event_dispatcher import EventDispatcher
from app.response_consumer import ResponseConsumer
from domain.entities import RoutingContext, TelegramEvent
from infrastructure.broker import Consumer, RabbitMQManager, Publisher
from infrastructure.config import AppConfig
from infrastructure.health import create_health_server
from infrastructure.telegram.client import TelegramClient


logger = structlog.get_logger()


class ReceiverService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._manager = RabbitMQManager(config.broker)
        self._publisher = Publisher(self._manager)
        self._dispatcher = EventDispatcher(config.bots, self._publisher)
        self._health_site: Any = None

        clients: dict[str, TelegramClient] = {}
        for bot_cfg in config.bots:
            client = TelegramClient(bot_cfg, self._on_event)
            clients[bot_cfg.name] = client
        self._clients = clients

        self._response_consumer = ResponseConsumer(self._clients)
        self._consumer = Consumer(
            self._manager,
            "outgoing.responses",
            self._response_consumer.handle,
            on_failed=self._on_response_failed,
        )

    async def _on_event(self, event: TelegramEvent, context: RoutingContext) -> None:
        await self._dispatcher.dispatch(event, context)

    async def _on_response_failed(self, body: dict[str, Any], exc: Exception) -> None:
        logger.error("response permanently failed", error=str(exc))

    async def start(self) -> None:
        await self._manager.connect()

        for client in self._clients.values():
            await client.start()

        try:
            await self._consumer.start()
        except Exception:
            logger.warning("response consumer not started", exc_info=True)

        self._health_site = await create_health_server(
            self._config.health_port,
            broker=self._manager,
            clients=list(self._clients.values()),
        )

        logger.info("receiver service started", bots=list(self._clients.keys()))

    async def stop(self) -> None:
        if self._health_site is not None:
            await self._health_site.stop()

        for client in self._clients.values():
            await client.stop()

        await self._consumer.stop()
        await self._manager.disconnect()
        logger.info("receiver service stopped")
