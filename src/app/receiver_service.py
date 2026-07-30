from __future__ import annotations

import asyncio
import sys
from typing import Any

import structlog


from app.wiring import build_components
from domain.schemas import AdminSignalType
from app.log_buffer import LogBuffer
from domain.entities import MediaConfigRule, RoutingContext, TelegramEvent
from infrastructure.broker import Consumer
from infrastructure.config import AppConfig
from infrastructure.health import create_health_server
from prometheus_client import Counter, Gauge

# Define Prometheus metrics
events_received = Counter("events_received", "Number of events received", ["bot"])
responses_failed = Counter("responses_failed", "Number of responses that failed")
client_connected = Gauge("client_connected", "Client connection status", ["bot"])
broker_connected = Gauge("broker_connected", "Broker connection status")


logger = structlog.get_logger()


class ReceiverService:
    def __init__(
        self,
        config: AppConfig,
        log_buffer: LogBuffer | None = None,
    ) -> None:
        self._config = config
        c = build_components(
            config,
            log_buffer,
            on_event=self._on_event,
            on_response_failed=self._on_response_failed,
            on_media_config_message=self._on_media_config_message,
            on_client_connected=self._on_client_connected,
            on_client_disconnected=self._on_client_disconnected,
            on_shutdown=self.shutdown,
            on_start=self.start,
            on_restart=self.restart,
        )
        self._manager = c.manager
        self._publisher = c.publisher
        self._metrics = c.metrics
        self._log_buffer = c.log_buffer
        self._dispatcher = c.dispatcher
        self._health_site: Any = None
        self._health_task: asyncio.Task[None] | None = None
        self._last_health: dict[str, bool] = {}
        self._last_client_health: dict[str, bool] = {}
        self._started = False
        self._running = False

        self._disconnect_timers: dict[str, asyncio.Task[None]] = {}
        self._disconnect_notified: set[str] = set()
        self._debounce_delay = 300  # seconds (5 min)

        self._clients = c.clients
        self._user_client = c.user_client

        self._cache = c.cache
        self._media_config = c.media_config
        self._upload_registry = c.upload_registry
        self._upload_storage = c.upload_storage

        self._notifier = c.notifier
        self._cmd_handler = c.cmd_handler

        self._media_downloader = c.media_downloader

        self._response_consumer = c.response_consumer
        self._consumer = c.consumer
        self._media_config_consumer = c.media_config_consumer

        self._bot_command_registry = c.bot_command_registry
        self._subscriber_handler = c.subscriber_handler
        self._sub_cmd_consumer = c.sub_cmd_consumer

    async def _on_event(self, event: TelegramEvent, context: RoutingContext) -> None:
        self._metrics.event_received(event.bot_id)
        events_received.labels(bot=event.bot_id).inc()
        await self._dispatcher.dispatch(event, context)
        try:
            await self._media_downloader.on_event(event, context)
        except Exception as exc:
            logger.exception("media downloader failed", bot=event.bot_id, exc=exc)
            # Re-raise to ensure failures aren't silently swallowed
            raise

    async def _on_response_failed(self, body: dict[str, Any], exc: Exception) -> None:
        logger.error("response permanently failed", error=str(exc))
        self._metrics.response_failed()
        responses_failed.inc()
        if self._notifier:
            await self._notifier.notify(
                AdminSignalType.RESPONSE_FAILED, body=body, exc=exc
            )

    async def _on_media_config_message(self, body: dict[str, Any]) -> None:
        try:
            rule = MediaConfigRule.model_validate(body)
            self._media_config.add_rule(rule)
        except Exception as exc:
            logger.warning(
                "invalid media config message", body=body, exc=exc, exc_info=True
            )
            if self._notifier:
                await self._notifier.notify(
                    AdminSignalType.CONFIG_WARNING,
                    message="Invalid media config message received via AMQP",
                    body=body,
                )

    async def _on_client_connected(self, name: str) -> None:
        logger.info("client connected", bot=name)
        client_connected.labels(bot=name).set(1)

        timer = self._disconnect_timers.pop(name, None)
        if timer is not None and not timer.done():
            timer.cancel()

    async def _on_client_disconnected(self, name: str) -> None:
        logger.warning("client disconnected", bot=name)
        client_connected.labels(bot=name).set(0)

        if name in self._disconnect_timers:
            return  # timer already running — counting from first disconnect

        timer = asyncio.create_task(self._disconnect_timeout(name))
        self._disconnect_timers[name] = timer

    async def _disconnect_timeout(self, name: str) -> None:
        try:
            await asyncio.sleep(self._debounce_delay)
        except asyncio.CancelledError:
            return

        self._disconnect_timers.pop(name, None)

        # Guard: client may have reconnected during the debounce window
        client = self._clients.get(name)
        if client is not None and await client.health():
            logger.info(
                "client reconnected during debounce window",
                bot=name,
                delay=self._debounce_delay,
            )
            return

        self._disconnect_notified.add(name)
        logger.warning(
            "client disconnected (confirmed)", bot=name, delay=self._debounce_delay
        )

        if self._notifier:
            await self._notifier.notify(
                AdminSignalType.COMPONENT_DISCONNECTED, component=name
            )

    async def _health_monitor(self) -> None:
        interval = 60.0
        min_interval = 60.0
        max_interval = 300.0
        while True:
            await asyncio.sleep(interval)

            try:
                broker_ok = await self._manager.health()
                broker_connected.set(1 if broker_ok else 0)
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

            for name, client in self._clients.items():
                try:
                    ok = await client.health()
                    prev = self._last_client_health.get(name)
                    if prev is not None and ok != prev:
                        await self._check_client_transition(name, ok)
                    self._last_client_health[name] = ok
                except Exception:
                    logger.exception("health check failed for client", bot=name)

            all_healthy = (
                self._last_health.get("broker", False)
                and self._last_health.get("admin_notifier", True)
                and all(self._last_client_health.values())
            )
            if all_healthy:
                interval = min(interval * 2, max_interval)
            else:
                interval = min_interval

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

    async def _check_client_transition(self, name: str, connected: bool) -> None:
        if connected:
            # Client reconnected — cancel any pending disconnect timer
            timer = self._disconnect_timers.pop(name, None)
            if timer is not None and not timer.done():
                timer.cancel()
            elif timer is None:
                # Timer was already cleaned up or never existed
                pass
            self._disconnect_notified.discard(name)
            logger.info("client reconnected", bot=name)
            if self._notifier:
                await self._notifier.notify(
                    AdminSignalType.COMPONENT_CONNECTED, component=name
                )
        else:
            # Client went silent — start debounce if not already running
            if name not in self._disconnect_timers:
                timer = asyncio.create_task(self._disconnect_timeout(name))
                self._disconnect_timers[name] = timer

    async def start(self) -> None:
        if self._running:
            logger.warning("receiver service already running")
            return

        try:
            await self._manager.connect()
        except Exception as exc:
            logger.error("broker manager failed to connect", exc=exc, exc_info=True)
            raise

        if self._notifier is not None:
            await self._notifier.start()
            self._health_task = asyncio.create_task(self._health_monitor())
            try:
                if self._cmd_handler is not None:
                    await self._cmd_handler.register_commands()
            except Exception as exc:
                logger.error("command registration failed", exc=exc, exc_info=True)
                raise

        failed_bots: list[str] = []
        for client in self._clients.values():
            try:
                await client.start()
            except Exception as exc:
                logger.error(
                    "client failed to start, skipping",
                    bot=client.bot_id,
                    exc=exc,
                    exc_info=True,
                )
                failed_bots.append(client.bot_id)
        for bot_id in failed_bots:
            self._clients.pop(bot_id, None)
        if failed_bots and self._notifier:
            await self._notifier.notify(
                AdminSignalType.COMPONENT_DISCONNECTED,
                component=f"bots/{','.join(failed_bots)}",
            )

        if self._user_client is not None:
            try:
                await self._user_client.start()
            except Exception as exc:
                logger.error(
                    "user client failed to start, disabling",
                    bot=self._user_client.bot_id,
                    exc=exc,
                    exc_info=True,
                )
                self._user_client = None

        await self._upload_registry.connect()

        try:
            await self._consumer.start()
        except Exception as exc:
            logger.error("response consumer failed to start", exc=exc, exc_info=True)
            raise

        try:
            mc = Consumer(
                self._manager,
                "media-config",
                self._on_media_config_message,
                routing_key="media-config",
            )
            await mc.start()
            self._media_config_consumer = mc
        except Exception as exc:
            logger.error(
                "media config consumer failed to start", exc=exc, exc_info=True
            )
            await self._consumer.stop()
            raise

        try:
            sc = Consumer(
                self._manager,
                "subscriber-commands",
                self._subscriber_handler.handle,
                routing_key="subscriber-commands",
            )
            await sc.start()
            self._sub_cmd_consumer = sc
        except Exception as exc:
            logger.error(
                "subscriber commands consumer failed to start", exc=exc, exc_info=True
            )
            if self._media_config_consumer is not None:
                await self._media_config_consumer.stop()
            await self._consumer.stop()
            raise

        self._health_site = await create_health_server(
            port=self._config.api_side_port,
            storage=self._cache,
            upload_registry=self._upload_registry,
            upload_storage=self._upload_storage,
            max_upload_size=self._config.max_upload_size,
            upload_rate_limit=self._config.upload_rate_limit,
            clients=list(self._clients.values()),
            client_map=self._clients,
            broker=self._manager,
        )

        self._started = True
        self._running = True

        logger.info(
            "receiver service started",
            bots=list(self._clients.keys()),
            admin=bool(self._notifier),
        )

    async def shutdown(self) -> None:
        if not self._running:
            logger.warning("receiver service not running, shutdown skipped")
            return

        if self._health_site is not None:
            await self._health_site.stop()
            self._health_site = None

        if self._health_task is not None:
            self._health_task.cancel()
            self._health_task = None

        for timer in self._disconnect_timers.values():
            if not timer.done():
                timer.cancel()
        self._disconnect_timers.clear()

        for client in self._clients.values():
            await client.stop()

        if self._media_config_consumer is not None:
            await self._media_config_consumer.stop()
        if self._sub_cmd_consumer is not None:
            await self._sub_cmd_consumer.stop()
        await self._consumer.stop()
        await self._upload_registry.close()
        await self._publisher.close()
        await self._manager.disconnect()
        self._running = False
        logger.info("receiver service stopped")

    async def stop(self) -> None:
        await self.shutdown()
        if self._notifier is not None:
            await self._notifier.stop()

    async def restart(self) -> None:
        await self.shutdown()
        logger.info("receiver service restarting — exiting with code 0")
        sys.exit(0)
