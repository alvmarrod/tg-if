from aiohttp import web


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "healthy"})


async def create_health_server(port: int) -> web.TCPSite:
    app = web.Application()
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return site
