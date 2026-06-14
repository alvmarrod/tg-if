from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

import structlog

from app.admin_commands import AdminCommandHandler
from app.admin_notifier import AdminNotifier, AdminSignalType
from app.event_dispatcher import EventDispatcher
from app.log_buffer import LogBuffer
from app.metrics import ServiceMetrics
from app.response_consumer import ResponseConsumer
from domain.entities import RoutingContext, TelegramEvent
from infrastructure.broker import Consumer, RabbitMQManager, Publisher
from infrastructure.config import AppConfig, BotConfig
from infrastructure.health import create_health_server
from infrastructure import metrics_exporter as prom
from infrastructure.telegram.client import TelegramClient


logger = structlog.get_logger()


class ReceiverService:
    def __init__(
        self,
        config: AppConfig,
        log_buffer: LogBuffer | None = None,
    ) -> None:
        self._config = config
        self._manager = RabbitMQManager(config.broker)
        self._publisher = Publisher(self._manager)
        self._metrics = ServiceMetrics()
        self._log_buffer = log_buffer
        self._dispatcher = EventDispatcher(
            config.bots, self._publisher, metrics=self._metrics
        )
        self._health_site: Any = None
        self._health_task: asyncio.Task[None] | None = None
        self._last_health: dict[str, bool] = {}

        clients: dict[str, TelegramClient] = {}
        for bot_cfg in config.bots:
            client = TelegramClient(
                bot_cfg,
                self._on_event,
                on_connect=partial(self._on_client_connected, bot_cfg.name),
                on_disconnect=partial(self._on_client_disconnected, bot_cfg.name),
            )
            clients[bot_cfg.name] = client
        self._clients = clients

        notifier: AdminNotifier | None = None
        cmd_handler: AdminCommandHandler | None = None
        if config.admin is not None:
            admin_bot_cfg = BotConfig(
                name=config.admin.name,
                api_id=config.admin.api_id,
                api_hash=config.admin.api_hash,
                session_file=config.admin.session_file,
            )
            admin_client = TelegramClient(admin_bot_cfg)
            notifier = AdminNotifier(config.admin, client=admin_client)
            cmd_handler = AdminCommandHandler(
                admin_client=admin_client,
                user_id=config.admin.user_id,
                clients=self._clients,
                manager=self._manager,
                config=config,
                metrics=self._metrics,
                log_buffer=self._log_buffer,
            )
            admin_client.set_event_callback(cmd_handler.handle)
        self._notifier = notifier
        self._cmd_handler = cmd_handler

        self._response_consumer = ResponseConsumer(self._clients, metrics=self._metrics)
        self._consumer = Consumer(
            self._manager,
            "outgoing.responses",
            self._response_consumer.handle,
            on_failed=self._on_response_failed,
        )

    async def _on_event(self, event: TelegramEvent, context: RoutingContext) -> None:
        self._metrics.event_received(event.bot_id)
        prom.events_received.labels(bot=event.bot_id).inc()
        await self._dispatcher.dispatch(event, context)

    async def _on_response_failed(self, body: dict[str, Any], exc: Exception) -> None:
        logger.error("response permanently failed", error=str(exc))
        self._metrics.response_failed()
        prom.responses_failed.inc()
        if self._notifier:
            await self._notifier.notify(
                AdminSignalType.RESPONSE_FAILED, body=body, exc=exc
            )

    async def _on_client_connected(self, name: str) -> None:
        logger.info("client connected", bot=name)
        prom.client_connected.labels(bot=name).set(1)
        if self._notifier:
            await self._notifier.notify(
                AdminSignalType.COMPONENT_CONNECTED, component=name
            )

    async def _on_client_disconnected(self, name: str) -> None:
        logger.warning("client disconnected", bot=name)
        prom.client_connected.labels(bot=name).set(0)
        if self._notifier:
            await self._notifier.notify(
                AdminSignalType.COMPONENT_DISCONNECTED, component=name
            )

    async def _health_monitor(self) -> None:
        while True:
            await asyncio.sleep(60)

            try:
                broker_ok = await self._manager.health()
                prom.broker_connected.set(1 if broker_ok else 0)
                await self._check_transition(
                    "broker", broker_ok, self._last_health.get("broker")
                )
                self._last_health["broker"] = broker_ok
            except Exception:
                logger.exception("health check failed for broker")

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
