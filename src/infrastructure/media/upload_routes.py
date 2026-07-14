from __future__ import annotations

import asyncio
import hashlib
import os
from typing import Any

import structlog
from aiohttp import web
from aiohttp.multipart import BodyPartReader
from aiohttp.web_app import AppKey  # type: ignore[attr-defined]

from domain.schemas import UploadEntry
from infrastructure.media.storage import MediaStorage
from infrastructure.sqlite import UploadRegistry


UploadRegistryKey: AppKey[UploadRegistry | None] = AppKey("upload_registry")
MediaStorageKey: AppKey[MediaStorage | None] = AppKey("upload_storage")
ClientMapKey: AppKey[dict[str, Any]] = AppKey("client_map")
MaxUploadSizeKey: AppKey[int] = AppKey("max_upload_size")

logger = structlog.get_logger()


_REQUIRED_HEADERS: set[str] = {"Content-Type"}


def _validate_upload_request(request: web.Request) -> web.Response | None:
    missing = _REQUIRED_HEADERS - set(request.headers)
    if missing:
        return web.json_response(
            {"error": "missing required headers", "missing": list(missing)},
            status=400,
        )
    ct = request.headers.get("Content-Type", "")
    if not ct.startswith("multipart/form-data"):
        return web.json_response(
            {"error": "Content-Type must be multipart/form-data"},
            status=400,
        )
    return None


_CT_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/x-msvideo": "avi",
    "video/x-matroska": "mkv",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
    "application/zip": "zip",
    "application/x-tar": "tar",
    "application/x-gzip": "gz",
    "application/gzip": "gz",
    "application/x-bzip2": "bz2",
    "application/x-7z-compressed": "7z",
    "application/pdf": "pdf",
    "application/octet-stream": "bin",
}


def _detect_ext(filename: str | None, content_type: str | None) -> str:
    if filename:
        _, ext = os.path.splitext(filename)
        if ext:
            return ext.lstrip(".").lower()
    if content_type:
        return _CT_TO_EXT.get(content_type, "bin")
    return "bin"


async def handle_upload_post(request: web.Request) -> web.Response:
    bot_id = request.match_info.get("bot_id", "")
    if not bot_id:
        return web.json_response({"error": "missing bot_id"}, status=400)

    registry: UploadRegistry | None = request.app.get(UploadRegistryKey)
    storage: MediaStorage | None = request.app.get(MediaStorageKey)
    client_map: dict[str, Any] = request.app.get(ClientMapKey, {})
    max_size: int = request.app.get(MaxUploadSizeKey, 2000 * 1024 * 1024)

    if registry is None or storage is None:
        return web.json_response({"error": "upload service not available"}, status=503)

    if bot_id not in client_map:
        return web.json_response({"error": f"unknown bot: {bot_id}"}, status=404)

    error = _validate_upload_request(request)
    if error is not None:
        return error

    reader = await request.multipart()
    part = await reader.next()
    if not isinstance(part, BodyPartReader):
        return web.json_response({"error": "missing file field"}, status=400)
    if part.name != "file":
        return web.json_response(
            {"error": "unexpected field, expected 'file'"}, status=400
        )

    data = await part.read()

    if len(data) > max_size:
        logger.warning(
            "upload rejected: file too large",
            bot=bot_id,
            size=len(data),
            max_size=max_size,
        )
        return web.json_response(
            {
                "error": "file too large",
                "size": len(data),
                "max_size": max_size,
            },
            status=413,
        )

    if len(data) == 0:
        return web.json_response({"error": "empty file"}, status=400)

    ext = _detect_ext(part.filename, part.headers.get("Content-Type"))
    content_hash = hashlib.sha256(data).hexdigest()
    upload_id = f"upl_{content_hash}"

    entry = await asyncio.to_thread(registry.get_by_hash, content_hash)
    if entry is not None:
        logger.info(
            "upload cache hit",
            bot=bot_id,
            content_hash=content_hash,
            has_file_id=entry.file_id is not None,
        )
        return web.json_response(
            {
                "upload_id": upload_id,
                "size": entry.size,
                "ext": entry.ext,
                "cached": True,
                "file_id": entry.file_id,
                "file_unique_id": entry.file_unique_id,
            }
        )

    path = await storage.store(bot_id, content_hash, data, ext)
    upload_entry = UploadEntry(
        content_hash=content_hash,
        bot_id=bot_id,
        ext=ext,
        size=len(data),
    )
    await asyncio.to_thread(registry.register, upload_entry)

    logger.info(
        "upload stored",
        bot=bot_id,
        content_hash=content_hash,
        size=len(data),
        ext=ext,
        path=path,
    )

    return web.json_response(
        {
            "upload_id": upload_id,
            "size": len(data),
            "ext": ext,
            "cached": False,
            "file_id": None,
            "file_unique_id": None,
        }
    )
