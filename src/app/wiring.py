"""Component wiring for ReceiverService.

Extracts ~130 lines of constructor dependency graph from receiver_service.py
into a pure assembly function, keeping the service class focused on lifecycle
and event dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import structlog

from app.admin_commands import AdminCommandHandler
from app.admin_notifier import AdminNotifier
from app.bot_command_registry import BotCommandRegistry
from app.chat_exporter import ChatExportEngine
from app.event_dispatcher import EventDispatcher
from app.log_buffer import LogBuffer
from app.media_config import MediaConfigManager
from app.media_downloader import MediaDownloader
from app.metrics import ServiceMetrics
from app.response_consumer import ResponseConsumer
from app.subscriber_command_handler import SubscriberCommandHandler
from infrastructure.broker import Consumer, Publisher, RabbitMQManager
from infrastructure.config import AppConfig, BotConfig
from infrastructure.media.storage import DiskStorage
from infrastructure.sqlite import UploadRegistry
from infrastructure.telegram.client import TelegramClient
from infrastructure.telegram.handlers import parse_session_path

logger = structlog.get_logger()


@dataclass
class ServiceComponents:
    """All wired infrastructure and application objects."""

    log_buffer: LogBuffer | None
    manager: RabbitMQManager
    publisher: Publisher
    metrics: ServiceMetrics
    dispatcher: EventDispatcher
    clients: dict[str, TelegramClient]
    user_client: TelegramClient | None
    cache: DiskStorage
    media_config: MediaConfigManager
    upload_registry: UploadRegistry
    upload_storage: DiskStorage
    notifier: AdminNotifier | None
    cmd_handler: AdminCommandHandler | None
    media_downloader: MediaDownloader
    response_consumer: ResponseConsumer
    consumer: Consumer
    media_config_consumer: Consumer | None
    bot_command_registry: BotCommandRegistry
    subscriber_handler: SubscriberCommandHandler
    sub_cmd_consumer: Consumer | None


def build_components(
    config: AppConfig,
    log_buffer: LogBuffer | None,
    on_event: Any,  # Callable[[TelegramEvent, RoutingContext], Awaitable[None]]
    on_response_failed: Any,
    on_media_config_message: Any,
    on_client_connected: Any,
    on_client_disconnected: Any,
    on_shutdown: Any,
    on_start: Any,
    on_restart: Any,
) -> ServiceComponents:
    """Construct and wire all service components from configuration."""

    manager = RabbitMQManager(config.broker)
    publisher = Publisher(manager)
    metrics = ServiceMetrics()
    dispatcher = EventDispatcher(
        config.bots,
        publisher,
        metrics=metrics,
        media_base_url=config.media_base_url,
    )

    clients: dict[str, TelegramClient] = {}
    for bot_cfg in config.bots:
        client = TelegramClient(
            bot_cfg,
            on_event,
            on_connect=partial(on_client_connected, bot_cfg.name),
            on_disconnect=partial(on_client_disconnected, bot_cfg.name),
        )
        clients[bot_cfg.name] = client

    user_client: TelegramClient | None = None
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
            user_client = TelegramClient(user_cfg)

    cache = DiskStorage(
        config.media_cache_path,
        max_tracked_files=config.media_max_tracked_files,
    )
    media_config = MediaConfigManager(config.media_config_path)
    upload_registry = UploadRegistry(config.upload_db_path)
    upload_storage = DiskStorage(
        config.upload_storage_path,
        max_tracked_files=config.media_max_tracked_files,
    )

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
            clients=clients,
            admin_client=admin_client,
            user_client=user_client,
        )
        cmd_handler = AdminCommandHandler(
            admin_client=admin_client,
            user_id=config.admin.user_id,
            clients=clients,
            manager=manager,
            config=config,
            metrics=metrics,
            dispatcher=dispatcher,
            log_buffer=log_buffer,
            media_config=media_config,
            storage=cache,
            upload_registry=upload_registry,
            upload_storage=upload_storage,
            chat_exporter=chat_exporter,
            on_shutdown=on_shutdown,
            on_start=on_start,
            on_restart=on_restart,
        )
        admin_client.set_event_callback(cmd_handler.handle)

    media_downloader = MediaDownloader(
        storage=cache,
        clients=clients,
        config=media_config,
        publisher=publisher,
        media_base_url=config.media_base_url,
    )

    response_consumer = ResponseConsumer(
        clients,
        manager,
        metrics=metrics,
        registry=upload_registry,
        upload_storage=upload_storage,
    )
    consumer = Consumer(
        manager,
        "outgoing.responses",
        response_consumer.handle,
        on_failed=on_response_failed,
        routing_key="response",
    )

    media_config_consumer: Consumer | None = None

    bot_command_registry = BotCommandRegistry()
    subscriber_handler = SubscriberCommandHandler(
        bot_command_registry, clients, manager
    )
    sub_cmd_consumer: Consumer | None = None

    return ServiceComponents(
        log_buffer=log_buffer,
        manager=manager,
        publisher=publisher,
        metrics=metrics,
        dispatcher=dispatcher,
        clients=clients,
        user_client=user_client,
        cache=cache,
        media_config=media_config,
        upload_registry=upload_registry,
        upload_storage=upload_storage,
        notifier=notifier,
        cmd_handler=cmd_handler,
        media_downloader=media_downloader,
        response_consumer=response_consumer,
        consumer=consumer,
        media_config_consumer=media_config_consumer,
        bot_command_registry=bot_command_registry,
        subscriber_handler=subscriber_handler,
        sub_cmd_consumer=sub_cmd_consumer,
    )
