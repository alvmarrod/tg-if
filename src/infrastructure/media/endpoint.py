import structlog
from aiohttp import web

from infrastructure.media.storage import MediaStorage, mime_for_ext
from infrastructure.telegram.client import TelegramClient


logger = structlog.get_logger()


async def handle_file_get(request: web.Request) -> web.Response:
    """Handle GET requests for media files."""
    bot_id = request.match_info.get("bot_id")
    file_unique_id = request.match_info.get("file_unique_id")
    file_id = request.query.get("file_id")

    if bot_id is None:
        return web.json_response({"error": "missing bot_id"}, status=400)

    if file_unique_id is None:
        return web.json_response({"error": "missing file_unique_id"}, status=400)

    client_map: dict[str, TelegramClient] | None = request.app.get("client_map")
    storage: MediaStorage | None = request.app.get("storage")

    if storage is None:
        return web.json_response({"error": "storage not available"}, status=503)

    # Check cache first
    data = await storage.retrieve(bot_id, file_unique_id)
    if data is not None:
        path = await storage.path_for(bot_id, file_unique_id)
        if path is None:
            return web.json_response({"error": "cached file has no path"}, status=500)
        if not path.exists():
            return web.json_response(
                {"error": "cached file path does not exist"}, status=500
            )
        ext = path.suffix.lstrip(".")
        if ext == "":
            return web.json_response(
                {"error": "cached file has no extension"}, status=500
            )
        return web.Response(body=data, content_type=mime_for_ext(ext))

    # Cache miss — need file_id and client to download from Telegram
    if file_id is None:
        return web.json_response(
            {"error": "file not cached and no file_id provided"}, status=404
        )

    if client_map is None:
        return web.json_response({"error": "client_map not available"}, status=503)

    client = client_map.get(bot_id)
    if client is None:
        return web.json_response({"error": f"unknown bot: {bot_id}"}, status=404)

    # Download from Telegram
    try:
        result = await client._client.download_media(file_id, in_memory=True)
    except Exception as exc:
        logger.warning(
            "media download failed",
            bot=bot_id,
            file_unique_id=file_unique_id,
            error=str(exc),
            exc_info=True,
        )
        return web.json_response(
            {"error": f"telegram download failed: {exc}"}, status=502
        )

    if result is None:
        return web.json_response({"error": "download returned no data"}, status=502)

    raw_data = (
        result.getvalue() if hasattr(result, "getvalue") else result.read()  # type: ignore[union-attr]
    )

    # Use bin as default; in-memory download lacks type metadata
    ext = "bin"

    if not await storage.store(bot_id, file_unique_id, raw_data, ext):
        return web.json_response({"error": "failed to store file"}, status=500)

    # Verify storage succeeded by attempting to retrieve
    verify_data = await storage.retrieve(bot_id, file_unique_id)
    if verify_data is None:
        return web.json_response({"error": "storage verification failed"}, status=500)

    # Also verify the path exists
    verify_path = await storage.path_for(bot_id, file_unique_id)
    if verify_path is None or not verify_path.exists():
        return web.json_response(
            {"error": "storage verification path failed"}, status=500
        )

    return web.Response(body=raw_data, content_type=mime_for_ext(ext))
