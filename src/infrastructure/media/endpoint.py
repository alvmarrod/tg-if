import structlog
from aiohttp import web

from infrastructure.media.storage import MediaStorage, mime_for_ext
from infrastructure.telegram.client import TelegramClient


logger = structlog.get_logger()


async def handle_file_get(request: web.Request) -> web.Response:
    bot_id = request.match_info.get("bot_id", "")
    file_unique_id = request.match_info.get("file_unique_id", "")
    file_id = request.query.get("file_id")

    if not bot_id or not file_unique_id:
        return web.json_response(
            {"error": "missing bot_id or file_unique_id"}, status=404
        )

    client_map: dict[str, TelegramClient] | None = request.app.get("client_map")
    storage: MediaStorage | None = request.app.get("storage")

    if storage is None:
        return web.json_response({"error": "storage not available"}, status=503)

    # Check cache first
    data = await storage.retrieve(bot_id, file_unique_id)
    if data is not None:
        path = await storage.path_for(bot_id, file_unique_id)
        ext = path.suffix.lstrip(".") if path else "bin"
        return web.Response(body=data, content_type=mime_for_ext(ext))

    # Cache miss — need file_id and client to download from Telegram
    if not file_id:
        return web.json_response(
            {"error": "file not cached and no file_id provided"}, status=404
        )

    if not client_map:
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
        )
        return web.json_response(
            {"error": f"telegram download failed: {exc}"}, status=502
        )

    if result is None:
        return web.json_response({"error": "telegram returned no data"}, status=502)

    raw: bytes = result.getvalue() if hasattr(result, "getvalue") else result.read()  # type: ignore[union-attr]
    if not isinstance(raw, bytes):
        raw = raw.encode() if isinstance(raw, str) else b""

    # Determine extension from content sniffing or default
    ext = "bin"
    if "photo" in str(file_id) or any(
        hint in str(file_id) for hint in ("photo", "image")
    ):
        ext = "jpg"

    await storage.store(bot_id, file_unique_id, raw, ext)

    return web.Response(body=raw, content_type=mime_for_ext(ext))
