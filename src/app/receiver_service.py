from __future__ import annotations

import asyncio
import sys
from functools import partial
from pathlib import Path
from typing import Any

import structlog

from app.admin_commands import AdminCommandHandler
from app.admin_notifier import AdminNotifier
from app.bot_command_registry import BotCommandRegistry
from app.chat_exporter import ChatExportEngine
from app.subscriber_command_handler import SubscriberCommandHandler
from domain.schemas import AdminSignalType
from app.event_dispatcher import EventDispatcher
from app.log_buffer import LogBuffer
from app.media_config import MediaConfigManager
from app.media_downloader import MediaDownloader
from app.metrics import ServiceMetrics
from app.response_consumer import ResponseConsumer
from domain.entities import MediaConfigRule, RoutingContext, TelegramEvent
from infrastructure.broker import Consumer, RabbitMQManager, Publisher
from infrastructure.config import AppConfig, BotConfig
from infrastructure.health import create_health_server
from infrastructure import metrics_exporter as prom
from infrastructure.media.storage import DiskStorage
from infrastructure.sqlite import UploadRegistry
from infrastructure.telegram.client import TelegramClient
from infrastructure.telegram.handlers import parse_session_path


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
            config.bots,
            self._publisher,
            metrics=self._metrics,
            media_base_url=config.media_base_url,
        )
        self._health_site: Any = None
        self._health_task: asyncio.Task[None] | None = None
        self._last_health: dict[str, bool] = {}
        self._started = False
        self._running = False

        self._disconnect_timers: dict[str, asyncio.Task[None]] = {}
        self._disconnect_notified: set[str] = set()
        self._debounce_delay = 300  # seconds (5 min)

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
        self._user_client: TelegramClient | None = None

        if config.user_account is not None:
            name, workdir = parse_session_path(config.user_account.session_file)
            session_path = Path(workdir) / f"{name}.session"
            if not session_path.exists():
                logger.warning(
                    "user session file not found, skipping user client",
                    path=str(session_path),
                    hint="run tools/auth_user.py to create the session interactively",
                )
            else:
                user_cfg = BotConfig(
                    name=config.user_account.name,
                    api_id=config.user_account.api_id,
                    api_hash=config.user_account.api_hash,
                    session_file=config.user_account.session_file,
                )
                self._user_client = TelegramClient(user_cfg)

        self._cache = DiskStorage(config.media_cache_path)
        self._media_config = MediaConfigManager(config.media_config_path)
        self._upload_registry = UploadRegistry(config.upload_db_path)
        self._upload_storage = DiskStorage(config.upload_storage_path)
        notifier: AdminNotifier | None = None
        cmd_handler: AdminCommandHandler | None = None
        if config.admin is not None:
            admin_bot_cfg = BotConfig(
                name=config.admin.name,
                api_id=config.admin.api_id,
                api_hash=config.admin.api_hash,
                session_file=config.admin.session_file,
                bot_token=config.admin.bot_token,
            )
            admin_client = TelegramClient(admin_bot_cfg)
            notifier = AdminNotifier(config.admin, client=admin_client)
            chat_exporter = ChatExportEngine(
                config=config,
                clients=self._clients,
                admin_client=admin_client,
                user_client=self._user_client,
            )
            cmd_handler = AdminCommandHandler(
                admin_client=admin_client,
                user_id=config.admin.user_id,
                clients=self._clients,
                manager=self._manager,
                config=config,
                metrics=self._metrics,
                dispatcher=self._dispatcher,
                log_buffer=self._log_buffer,
                media_config=self._media_config,
                storage=self._cache,
                upload_registry=self._upload_registry,
                upload_storage=self._upload_storage,
                chat_exporter=chat_exporter,
                on_shutdown=self.shutdown,
                on_start=self.start,
                on_restart=self.restart,
            )
            admin_client.set_event_callback(cmd_handler.handle)
        self._notifier = notifier
        self._cmd_handler = cmd_handler

        self._media_downloader = MediaDownloader(
            storage=self._cache,
            clients=self._clients,
            config=self._media_config,
            publisher=self._publisher,
            media_base_url=config.media_base_url,
        )

        self._response_consumer = ResponseConsumer(
            self._clients,
            self._manager,
            metrics=self._metrics,
            registry=self._upload_registry,
            upload_storage=self._upload_storage,
        )
        self._consumer = Consumer(
            self._manager,
            "outgoing.responses",
            self._response_consumer.handle,
            on_failed=self._on_response_failed,
            routing_key="response",
        )
        self._media_config_consumer: Consumer | None = None
        self._bot_command_registry = BotCommandRegistry()
        self._subscriber_handler = SubscriberCommandHandler(
            self._bot_command_registry,
            self._clients,
            self._manager,
        )
        self._sub_cmd_consumer: Consumer | None = None

    async def _on_event(self, event: TelegramEvent, context: RoutingContext) -> None:
        self._metrics.event_received(event.bot_id)
        prom.events_received.labels(bot=event.bot_id).inc()
        await self._dispatcher.dispatch(event, context)
        try:
            await self._media_downloader.on_event(event, context)
        except Exception:
            logger.exception("media downloader failed", bot=event.bot_id)

    async def _on_response_failed(self, body: dict[str, Any], exc: Exception) -> None:
        logger.error("response permanently failed", error=str(exc))
        self._metrics.response_failed()
        prom.responses_failed.inc()
        if self._notifier:
            await self._notifier.notify(
                AdminSignalType.RESPONSE_FAILED, body=body, exc=exc
            )

    async def _on_media_config_message(self, body: dict[str, Any]) -> None:
        try:
            rule = MediaConfigRule.model_validate(body)
            self._media_config.add_rule(rule)
        except Exception:
            logger.warning("invalid media config message", body=body, exc_info=True)
            if self._notifier:
                await self._notifier.notify(
                    AdminSignalType.CONFIG_WARNING,
                    message="Invalid media config message received via AMQP",
                    body=body,
                )

    async def _on_client_connected(self, name: str) -> None:
        logger.info("client connected", bot=name)
        prom.client_connected.labels(bot=name).set(1)

        timer = self._disconnect_timers.pop(name, None)
        if timer is not None and not timer.done():
            timer.cancel()

        if self._notifier and name in self._disconnect_notified:
            self._disconnect_notified.discard(name)
            await self._notifier.notify(
                AdminSignalType.COMPONENT_CONNECTED, component=name
            )

    async def _on_client_disconnected(self, name: str) -> None:
        logger.warning("client disconnected", bot=name)
        prom.client_connected.labels(bot=name).set(0)

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
        self._disconnect_notified.add(name)
        logger.warning(
            "client disconnected (confirmed)", bot=name, delay=self._debounce_delay
        )

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
        if self._running:
            logger.warning("receiver service already running")
            return

        await self._manager.connect()

        if not self._started:
            if self._notifier:
                await self._notifier.start()
                self._health_task = asyncio.create_task(self._health_monitor())
                if self._cmd_handler:
                    await self._cmd_handler.register_commands()

        for client in self._clients.values():
            await client.start()

        if self._user_client is not None:
            await self._user_client.start()

        self._upload_registry.connect()

        try:
            await self._consumer.start()
        except Exception:
            logger.warning("response consumer not started", exc_info=True)

        try:
            mc = Consumer(
                self._manager,
                "media-config",
                self._on_media_config_message,
                routing_key="media-config",
            )
            await mc.start()
            self._media_config_consumer = mc
        except Exception:
            logger.warning("media config consumer not started", exc_info=True)

        try:
            sc = Consumer(
                self._manager,
                "subscriber-commands",
                self._subscriber_handler.handle,
                routing_key="subscriber-commands",
            )
            await sc.start()
            self._sub_cmd_consumer = sc
        except Exception:
            logger.warning("subscriber commands consumer not started", exc_info=True)

        self._health_site = await create_health_server(
            self._config.api_side_port,
            broker=self._manager,
            clients=list(self._clients.values()),
            client_map=self._clients,
            storage=self._cache,
            upload_registry=self._upload_registry,
            upload_storage=self._upload_storage,
            max_upload_size=self._config.max_upload_size,
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
        self._upload_registry.close()
        await self._manager.disconnect()
        self._running = False
        logger.info("receiver service stopped")

    async def stop(self) -> None:
        await self.shutdown()
        if self._notifier:
            await self._notifier.stop()

    async def restart(self) -> None:
        await self.shutdown()
        logger.info("receiver service restarting — exiting with code 0")
        sys.exit(0)
