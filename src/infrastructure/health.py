import sys
from collections.abc import Iterable
from typing import Any

from aiohttp import web
from aiohttp.web import AppKey

from infrastructure.media.endpoint import handle_file_get
from infrastructure.media.rate_limiter import (
    _UploadRateLimiterKey,
    _SlidingWindowLimiter,
    upload_rate_limit_middleware,
)
from infrastructure.media.storage import MediaStorage
from infrastructure.media.upload_routes import (
    BrokerKey,
    ClientMapKey,
    ClientsKey,
    MaxUploadSizeKey,
    MediaStorageKey,
    StorageKey,
    UploadRegistryKey,
    handle_upload_post,
)
from infrastructure.sqlite import UploadRegistry
from infrastructure.telegram.client import TelegramClient


async def handle_health(request: web.Request) -> web.Response:
    status: dict[str, Any] = {"status": "healthy"}
    broker = request.app.get(BrokerKey)
    if broker is not None:
        broker_ok = await broker.health()
        status["broker"] = "connected" if broker_ok else "disconnected"
    clients = request.app.get(ClientsKey)
    if clients is not None:
        client_status: dict[str, str] = {}
        if isinstance(clients, dict):
            for bot_id, c in clients.items():
                if not hasattr(c, "health"):
                    raise TypeError(
                        f"Expected client object with health method, got {type(c).__name__}"
                    )
                ok = await c.health()
                client_status[bot_id] = "connected" if ok else "disconnected"
        elif isinstance(clients, Iterable) and not isinstance(clients, str):
            for c in clients:
                if not hasattr(c, "bot_id"):
                    raise TypeError(
                        f"Expected client object with bot_id attribute, got {type(c).__name__}"
                    )
                ok = await c.health()
                client_status[c.bot_id] = "connected" if ok else "disconnected"
        else:
            raise TypeError(
                f"Expected dict or iterable of clients, got {type(clients).__name__}"
            )
        status["clients"] = client_status
    return web.json_response(status)


async def handle_metrics(request: web.Request) -> web.Response:
    from infrastructure.metrics_exporter import generate_metrics

    return web.Response(
        text=generate_metrics(),
        content_type="text/plain; version=0.0.4",
    )


async def create_health_server(
    port: int,
    storage: MediaStorage | None = None,
    upload_registry: UploadRegistry | None = None,
    upload_storage: MediaStorage | None = None,
    max_upload_size: int = 2000 * 1024 * 1024,
    upload_rate_limit: int = 0,
    client_map: dict[str, TelegramClient] | None = None,
    **kwargs: Any,
) -> web.TCPSite:
    app = web.Application(client_max_size=sys.maxsize)
    if upload_rate_limit > 0:
        app[_UploadRateLimiterKey] = _SlidingWindowLimiter(
            max_requests=upload_rate_limit, window_seconds=60.0
        )
        app.middlewares.append(upload_rate_limit_middleware)  # type: ignore[arg-type]
    if storage is not None:
        app[StorageKey] = storage
    if upload_registry is not None:
        app[UploadRegistryKey] = upload_registry
    if upload_storage is not None:
        app[MediaStorageKey] = upload_storage
    app[MaxUploadSizeKey] = max_upload_size
    if client_map is not None:
        app[ClientMapKey] = client_map
    for key, val in kwargs.items():
        app[AppKey(key)] = val
    app.router.add_get("/health", handle_health)
    app.router.add_get("/metrics", handle_metrics)
    app.router.add_get("/files/{bot_id}/{file_unique_id}", handle_file_get)
    app.router.add_post("/upload/{bot_id}", handle_upload_post)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return site
