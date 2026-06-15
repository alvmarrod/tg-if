from collections.abc import Iterable
from typing import Any

from aiohttp import web

from infrastructure.media.endpoint import handle_file_get
from infrastructure.media.storage import MediaStorage


async def handle_health(request: web.Request) -> web.Response:
    status: dict[str, Any] = {"status": "healthy"}
    broker = request.app.get("broker")
    if broker is not None:
        broker_ok = await broker.health()
        status["broker"] = "connected" if broker_ok else "disconnected"
    clients = request.app.get("clients")
    if clients is not None:
        client_status: dict[str, str] = {}
        iterable: Iterable[Any] = clients
        if isinstance(clients, dict):
            iterable = clients.values()
        for c in iterable:
            ok = await c.health()
            client_status[c.bot_id] = "connected" if ok else "disconnected"
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
    **kwargs: Any,
) -> web.TCPSite:
    app = web.Application()
    for key, val in kwargs.items():
        app[key] = val
    if storage is not None:
        app["storage"] = storage
    app.router.add_get("/health", handle_health)
    app.router.add_get("/metrics", handle_metrics)
    app.router.add_get("/files/{bot_id}/{file_unique_id}", handle_file_get)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return site
