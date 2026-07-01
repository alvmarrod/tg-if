from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from aio_pika import Message

from app.metrics import ServiceMetrics
from domain.entities import OutgoingResponse, OutgoingResponseResult
from infrastructure import metrics_exporter as prom
from infrastructure.broker.rabbitmq import RabbitMQManager
from infrastructure.media.storage import MediaStorage
from infrastructure.sqlite import UploadRegistry
from infrastructure.telegram.client import TelegramClient
from pyrogram.errors import (
    ChatForbidden,
    ChatIdInvalid,
    ChatSendAudiosForbidden,
    MessageDeleteForbidden,
    ChatSendDocsForbidden,
    ChatSendGifsForbidden,
    ChatSendInlineForbidden,
    ChatSendMediaForbidden,
    ChatSendPhotosForbidden,
    ChatSendPlainForbidden,
    ChatSendPollForbidden,
    ChatSendStickersForbidden,
    ChatSendVideosForbidden,
    ChatSendVoicesForbidden,
    ChatWriteForbidden,
    ChannelBanned,
    ChannelPrivate,
    FloodWait,
    InputUserDeactivated,
    MediaEmpty,
    MediaInvalid,
    MessageEditTimeExpired,
    MessageIdInvalid,
    MessageNotModified,
    PeerFlood,
    PeerIdInvalid,
    PeerIdNotSupported,
    PrivacyPremiumRequired,
    ReplyMarkupInvalid,
    SendMessageMediaInvalid,
    SlowmodeWait,
    Timeout,
    UserBlocked,
    UserDeleted,
    UserIdInvalid,
    UserIsBlocked,
    UserIsBot,
    UserKicked,
    UserNotMutualContact,
    UserPrivacyRestricted,
    UserRestricted,
    YouBlockedUser,
    ServiceUnavailable,
)


TERMINAL_ERRORS = (
    ChatForbidden,
    ChatIdInvalid,
    ChatSendAudiosForbidden,
    ChatSendDocsForbidden,
    ChatSendGifsForbidden,
    ChatSendInlineForbidden,
    ChatSendMediaForbidden,
    ChatSendPhotosForbidden,
    ChatSendPlainForbidden,
    ChatSendPollForbidden,
    ChatSendStickersForbidden,
    ChatSendVideosForbidden,
    ChatSendVoicesForbidden,
    ChatWriteForbidden,
    ChannelBanned,
    ChannelPrivate,
    InputUserDeactivated,
    MediaEmpty,
    MediaInvalid,
    MessageEditTimeExpired,
    MessageIdInvalid,
    MessageNotModified,
    PeerFlood,
    PeerIdInvalid,
    PeerIdNotSupported,
    PrivacyPremiumRequired,
    ReplyMarkupInvalid,
    SendMessageMediaInvalid,
    UserBlocked,
    UserDeleted,
    UserIdInvalid,
    UserIsBlocked,
    UserIsBot,
    UserKicked,
    UserNotMutualContact,
    UserPrivacyRestricted,
    UserRestricted,
    YouBlockedUser,
)

TRANSIENT_ERRORS = (
    FloodWait,
    SlowmodeWait,
    ServiceUnavailable,
    Timeout,
)

TERMINAL_DELETE_ERRORS = (MessageDeleteForbidden,)

logger = structlog.get_logger()


_UPLOAD_KEYS: set[str] = {"photo", "video", "document", "audio"}


class ResponseConsumer:
    def __init__(
        self,
        clients: dict[str, TelegramClient],
        manager: RabbitMQManager,
        metrics: ServiceMetrics | None = None,
        registry: UploadRegistry | None = None,
        upload_storage: MediaStorage | None = None,
    ) -> None:
        self._clients = clients
        self._manager = manager
        self._metrics = metrics
        self._registry = registry
        self._upload_storage = upload_storage

    async def handle(self, body: dict[str, Any]) -> None:
        response = OutgoingResponse.model_validate(body)
        client = self._clients.get(response.bot_id)
        if not client:
            logger.error("unknown bot in response", bot_id=response.bot_id)
            await self._publish_result(
                response.reply_to,
                OutgoingResponseResult(
                    response_id=response.response_id,
                    correlation_id=response.correlation_id,
                    bot_id=response.bot_id,
                    chat_id=response.chat_id,
                    status="failed",
                    error_type="UNKNOWN_BOT",
                    error_message=f"no client for bot '{response.bot_id}'",
                ),
            )
            return

        if self._metrics:
            self._metrics.response_consumed()
        prom.responses_consumed.inc()

        await self._send(client, response)

    async def _resolve_upload(self, bot_id: str, value: str) -> tuple[str, str | None]:
        if not value.startswith("upl_"):
            return value, None
        content_hash = value[4:]
        if self._registry is not None:
            entry = await asyncio.to_thread(self._registry.get_by_hash, content_hash)
            if entry is not None:
                if entry.file_id is not None:
                    await asyncio.to_thread(self._registry.touch_usage, content_hash)
                    return entry.file_id, content_hash
        if self._upload_storage is not None:
            path = await self._upload_storage.path_for(bot_id, content_hash)
            if path is not None:
                return str(path), content_hash
        logger.error(
            "upload not found",
            bot_id=bot_id,
            content_hash=content_hash,
        )
        msg = f"upload {value} not found — upload the file via POST /upload/{bot_id} first"
        raise ValueError(msg)

    def _extract_file_id(
        self,
        result: Any,
        rtype: str,
    ) -> list[tuple[str, str]]:
        media_attr = {
            "photo": "photo",
            "video": "video",
            "document": "document",
            "audio": "audio",
        }.get(rtype)
        if media_attr is None:
            return []
        media = getattr(result, media_attr, None)
        if media is None:
            return []
        file_id = getattr(media, "file_id", None)
        file_unique_id = getattr(media, "file_unique_id", None)
        if file_id and file_unique_id:
            return [(file_id, file_unique_id)]
        return []

    def _extract_file_ids_from_group(self, results: list[Any]) -> list[tuple[str, str]]:
        extracted: list[tuple[str, str]] = []
        for msg in results:
            for attr in ("photo", "video", "document", "audio"):
                media = getattr(msg, attr, None)
                if media is None:
                    continue
                fid = getattr(media, "file_id", None)
                fuid = getattr(media, "file_unique_id", None)
                if fid and fuid:
                    extracted.append((fid, fuid))
                break
        return extracted

    async def _send(self, client: TelegramClient, response: OutgoingResponse) -> None:
        rtype = response.response_type
        if rtype.startswith(("edit_", "answer_", "delete_")):
            method_name = rtype
        else:
            method_name = f"send_{rtype}"
        method = getattr(client, method_name, None)
        if not method:
            logger.error(
                "unknown response type",
                bot_id=response.bot_id,
                response_type=response.response_type,
            )
            return

        kwargs = dict(response.payload)
        if rtype == "delete_message":
            if "message_id" in kwargs and "message_ids" not in kwargs:
                kwargs["message_ids"] = kwargs.pop("message_id")
        resolved_hashes: list[str] = []
        for key in _UPLOAD_KEYS:
            if key in kwargs:
                resolved, ch = await self._resolve_upload(response.bot_id, kwargs[key])
                kwargs[key] = resolved
                if ch:
                    resolved_hashes.append(ch)
        if "media" in kwargs:
            new_media: list[dict[str, Any]] = []
            for item in kwargs["media"]:
                item = dict(item)
                if "media" in item:
                    resolved, ch = await self._resolve_upload(
                        response.bot_id, item["media"]
                    )
                    item["media"] = resolved
                    if ch:
                        resolved_hashes.append(ch)
                new_media.append(item)
            kwargs["media"] = new_media

        try:
            if rtype == "answer_callback_query":
                result = await method(**kwargs)
            else:
                result = await method(chat_id=response.chat_id, **kwargs)
            if self._metrics:
                self._metrics.response_sent()
            prom.responses_sent.inc()
            logger.info(
                "response sent",
                bot_id=response.bot_id,
                response_type=response.response_type,
            )
            message_id = getattr(result, "id", None) if result is not None else None
            await self._publish_result(
                response.reply_to,
                OutgoingResponseResult(
                    response_id=response.response_id,
                    correlation_id=response.correlation_id,
                    bot_id=response.bot_id,
                    chat_id=response.chat_id,
                    message_id=message_id,
                    status="delivered",
                ),
            )
            if self._registry and resolved_hashes:
                await self._update_after_send(rtype, result, resolved_hashes)
        except TRANSIENT_ERRORS:
            logger.warning(
                "transient send error, will retry",
                bot_id=response.bot_id,
                response_type=response.response_type,
                exc_info=True,
            )
            raise
        except TERMINAL_DELETE_ERRORS as exc:
            logger.warning(
                "terminal delete error, not retrying",
                bot_id=response.bot_id,
                response_type=response.response_type,
                error_type=exc.ID,
            )
            await self._publish_result(
                response.reply_to,
                OutgoingResponseResult(
                    response_id=response.response_id,
                    correlation_id=response.correlation_id,
                    bot_id=response.bot_id,
                    chat_id=response.chat_id,
                    status="failed",
                    error_type=exc.ID,
                    error_message=str(exc),
                ),
            )
        except TERMINAL_ERRORS as exc:
            logger.warning(
                "terminal send error, not retrying",
                bot_id=response.bot_id,
                response_type=response.response_type,
                error_type=exc.ID,
            )
            await self._publish_result(
                response.reply_to,
                OutgoingResponseResult(
                    response_id=response.response_id,
                    correlation_id=response.correlation_id,
                    bot_id=response.bot_id,
                    chat_id=response.chat_id,
                    status="failed",
                    error_type=exc.ID,
                    error_message=str(exc),
                ),
            )
        except Exception:
            logger.exception(
                "response send failed",
                bot_id=response.bot_id,
                response_type=response.response_type,
            )
            raise

    async def _update_after_send(
        self,
        rtype: str,
        result: Any,
        resolved_hashes: list[str],
    ) -> None:
        if self._registry is None:
            return
        file_ids: list[tuple[str, str]] = []
        if rtype == "media_group" and isinstance(result, list):
            file_ids = self._extract_file_ids_from_group(result)
        else:
            file_ids = self._extract_file_id(result, rtype)
        if not file_ids or not resolved_hashes:
            return
        for entry_hash, (fid, fuid) in zip(resolved_hashes, file_ids):
            await asyncio.to_thread(
                self._registry.update_file_id, entry_hash, fid, fuid
            )
            logger.info(
                "file_id registered for upload",
                content_hash=entry_hash,
                file_id=fid,
            )

    async def _publish_result(
        self,
        reply_to: str | None,
        result: OutgoingResponseResult,
    ) -> None:
        if not reply_to:
            return
        conn = self._manager.connection
        if not conn or conn.is_closed:
            logger.warning("cannot publish result: broker not connected")
            return
        channel = await conn.channel()
        try:
            await channel.default_exchange.publish(
                Message(
                    body=json.dumps(result.model_dump(mode="json")).encode(),
                    delivery_mode=2,
                ),
                routing_key=reply_to,
            )
            logger.debug(
                "result published to reply_to",
                reply_to=reply_to,
                status=result.status,
            )
        finally:
            await channel.close()
