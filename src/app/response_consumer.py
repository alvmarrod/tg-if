from __future__ import annotations

import json
from typing import Any

import structlog
from aio_pika import Message

from app.metrics import ServiceMetrics
from domain.entities import OutgoingResponse, OutgoingResponseResult
from infrastructure import metrics_exporter as prom
from infrastructure.broker.rabbitmq import RabbitMQManager
from infrastructure.telegram.client import TelegramClient
from pyrogram.errors import (
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

logger = structlog.get_logger()


class ResponseConsumer:
    def __init__(
        self,
        clients: dict[str, TelegramClient],
        manager: RabbitMQManager,
        metrics: ServiceMetrics | None = None,
    ) -> None:
        self._clients = clients
        self._manager = manager
        self._metrics = metrics

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

    async def _send(self, client: TelegramClient, response: OutgoingResponse) -> None:
        rtype = response.response_type
        if rtype.startswith(("edit_", "answer_")):
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

        try:
            kwargs = response.payload
            if rtype == "answer_callback_query":
                await method(**kwargs)
            else:
                await method(chat_id=response.chat_id, **kwargs)
            if self._metrics:
                self._metrics.response_sent()
            prom.responses_sent.inc()
            logger.info(
                "response sent",
                bot_id=response.bot_id,
                response_type=response.response_type,
            )
            await self._publish_result(
                response.reply_to,
                OutgoingResponseResult(
                    response_id=response.response_id,
                    correlation_id=response.correlation_id,
                    bot_id=response.bot_id,
                    chat_id=response.chat_id,
                    status="delivered",
                ),
            )
        except TRANSIENT_ERRORS:
            logger.warning(
                "transient send error, will retry",
                bot_id=response.bot_id,
                response_type=response.response_type,
                exc_info=True,
            )
            raise
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
