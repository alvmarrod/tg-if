from typing import Any

from aiohttp import web


async def handle_health(request: web.Request) -> web.Response:
    status: dict[str, Any] = {"status": "healthy"}
    broker = request.app.get("broker")
    if broker is not None:
        broker_ok = await broker.health()
        status["broker"] = "connected" if broker_ok else "disconnected"
    return web.json_response(status)


async def create_health_server(port: int, **kwargs: Any) -> web.TCPSite:
    app = web.Application()
    for key, val in kwargs.items():
        app[key] = val
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return site
