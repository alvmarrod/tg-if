from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.admin_notifier import AdminNotifier, AdminSignalType
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
        self._health_task: asyncio.Task[None] | None = None
        self._last_health: dict[str, bool] = {}

        clients: dict[str, TelegramClient] = {}
        for bot_cfg in config.bots:
            client = TelegramClient(bot_cfg, self._on_event)
            clients[bot_cfg.name] = client
        self._clients = clients

        notifier: AdminNotifier | None = None
        if config.admin is not None:
            notifier = AdminNotifier(config.admin)
        self._notifier = notifier

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
        if self._notifier:
            await self._notifier.notify(
                AdminSignalType.RESPONSE_FAILED, body=body, exc=exc
            )

    async def _health_monitor(self) -> None:
        while True:
            await asyncio.sleep(60)

            try:
                broker_ok = await self._manager.health()
                await self._check_transition(
                    "broker", broker_ok, self._last_health.get("broker")
                )
                self._last_health["broker"] = broker_ok
            except Exception:
                logger.exception("health check failed for broker")

            for name, client in self._clients.items():
                try:
                    ok = await client.health()
                    await self._check_transition(name, ok, self._last_health.get(name))
                    self._last_health[name] = ok
                except Exception:
                    logger.exception("health check failed", client=name)

            if self._notifier:
                try:
                    ok = await self._notifier.health()
                    await self._check_transition(
                        "admin_notifier", ok, self._last_health.get("admin_notifier")
                    )
                    self._last_health["admin_notifier"] = ok
                except Exception:
                    logger.exception("health check failed for admin_notifier")

    async def _check_transition(
        self, name: str, current: bool, previous: bool | None
    ) -> None:
        if previous is None or current == previous or self._notifier is None:
            return
        signal = (
            AdminSignalType.COMPONENT_CONNECTED
            if current
            else AdminSignalType.COMPONENT_DISCONNECTED
        )
        await self._notifier.notify(signal, component=name)

    async def start(self) -> None:
        await self._manager.connect()

        for client in self._clients.values():
            await client.start()

        if self._notifier:
            await self._notifier.start()
            self._health_task = asyncio.create_task(self._health_monitor())

        try:
            await self._consumer.start()
        except Exception:
            logger.warning("response consumer not started", exc_info=True)

        self._health_site = await create_health_server(
            self._config.health_port,
            broker=self._manager,
            clients=list(self._clients.values()),
        )

        logger.info(
            "receiver service started",
            bots=list(self._clients.keys()),
            admin=bool(self._notifier),
        )

    async def stop(self) -> None:
        if self._health_site is not None:
            await self._health_site.stop()

        if self._health_task is not None:
            self._health_task.cancel()
            self._health_task = None

        for client in self._clients.values():
            await client.stop()

        if self._notifier:
            await self._notifier.stop()

        await self._consumer.stop()
        await self._manager.disconnect()
        logger.info("receiver service stopped")
