from __future__ import annotations

import hashlib
import os
from typing import Any

import structlog
from aiohttp import web
from aiohttp.multipart import BodyPartReader
from aiohttp.web import AppKey

from domain.schemas import UploadEntry
from infrastructure.media.storage import MediaStorage
from infrastructure.sqlite import UploadRegistry
from infrastructure.telegram.client import TelegramClient


UploadRegistryKey: AppKey[UploadRegistry | None] = AppKey("upload_registry")
MediaStorageKey: AppKey[MediaStorage | None] = AppKey("upload_storage")
ClientMapKey: AppKey[dict[str, TelegramClient]] = AppKey("client_map")
MaxUploadSizeKey: AppKey[int] = AppKey("max_upload_size")
BrokerKey: AppKey[Any] = AppKey("broker")
ClientsKey: AppKey[Any] = AppKey("clients")
StorageKey: AppKey[MediaStorage | None] = AppKey("storage")

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
        if content_type not in _CT_TO_EXT:
            raise ValueError(
                f"Unknown content type: {content_type}. "
                f"Supported types: {list(_CT_TO_EXT.keys())}"
            )
        return _CT_TO_EXT[content_type]
    raise ValueError("Could not determine file extension from filename or content-type")


async def handle_upload_post(request: web.Request) -> web.Response:
    bot_id = request.match_info.get("bot_id")
    if bot_id is None:
        return web.json_response({"error": "missing bot_id"}, status=400)

    registry: UploadRegistry | None = request.app.get(UploadRegistryKey)
    storage: MediaStorage | None = request.app.get(MediaStorageKey)
    client_map = request.app.get(ClientMapKey)
    if client_map is None:
        return web.json_response(
            {"error": "client map not configured"},
            status=500,
        )
    max_size: int | None = request.app.get(MaxUploadSizeKey)
    if max_size is None:
        return web.json_response(
            {"error": "max_upload_size not configured"},
            status=500,
        )

    if registry is None or storage is None:
        return web.json_response({"error": "upload service not available"}, status=503)

    if bot_id not in client_map:
        return web.json_response({"error": f"unknown bot: {bot_id}"}, status=404)

    error = _validate_upload_request(request)
    if error is not None:
        return error

    try:
        reader = await request.multipart()
        part = await reader.next()
        if part is None:
            logger.warning(
                "upload multipart part is None",
                bot=bot_id,
            )
            return web.json_response(
                {"error": "unexpected multipart part: None"},
                status=400,
            )
        if not isinstance(part, BodyPartReader):
            logger.warning(
                "upload multipart part is not BodyPartReader",
                bot=bot_id,
                type=type(part).__name__,
            )
            return web.json_response(
                {"error": "unexpected multipart part type"},
                status=400,
            )
        if part.name != "file":
            return web.json_response(
                {"error": "unexpected field, expected 'file'"}, status=400
            )

        data = await part.read()
    except Exception as e:
        logger.error(
            "upload multipart parsing failed",
            bot=bot_id,
            error=str(e),
        )
        return web.json_response(
            {"error": "failed to parse multipart form", "details": str(e)},
            status=400,
        )

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

    try:
        ext = _detect_ext(part.filename, part.headers.get("Content-Type"))
    except ValueError as e:
        logger.warning(
            "upload rejected: invalid file type",
            bot=bot_id,
            error=str(e),
        )
        return web.json_response(
            {"error": "unsupported file type", "details": str(e)},
            status=415,
        )

    content_hash = hashlib.sha256(data).hexdigest()
    upload_id = f"upl_{content_hash}"

    try:
        entry = await registry.get_by_hash(content_hash)
    except Exception as e:
        logger.error(
            "upload registry lookup failed",
            bot=bot_id,
            content_hash=content_hash,
            error=str(e),
        )
        return web.json_response(
            {"error": "failed to check upload cache", "details": str(e)},
            status=500,
        )

    if entry:
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

    try:
        path = await storage.store(bot_id, content_hash, data, ext)
    except Exception as e:
        logger.error(
            "upload storage failed",
            bot=bot_id,
            content_hash=content_hash,
            error=str(e),
        )
        return web.json_response(
            {"error": "failed to store file", "details": str(e)},
            status=500,
        )

    upload_entry = UploadEntry(
        content_hash=content_hash,
        bot_id=bot_id,
        ext=ext,
        size=len(data),
    )
    await registry.register(upload_entry)

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
