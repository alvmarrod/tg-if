from __future__ import annotations

import asyncio

import structlog

from app.media_config import MediaConfigManager
from domain.entities import MediaReadyEvent, MessageEvent, RoutingContext, TelegramEvent
from infrastructure.broker import Publisher
from infrastructure.media.storage import MediaStorage
from infrastructure.telegram.client import TelegramClient


logger = structlog.get_logger()


_MEDIA_EXTENSION: dict[str, str] = {
    "photo": "jpg",
    "video": "mp4",
    "audio": "mp3",
    "document": "bin",
    "animation": "gif",
    "voice": "ogg",
    "video_note": "mp4",
    "sticker": "webp",
}


class MediaDownloader:
    def __init__(
        self,
        *,
        storage: MediaStorage,
        clients: dict[str, TelegramClient],
        config: MediaConfigManager,
        publisher: Publisher | None = None,
        media_base_url: str = "http://localhost:8080",
    ) -> None:
        self._storage = storage
        self._clients = clients
        self._config = config
        self._publisher = publisher
        self._media_base_url = media_base_url.rstrip("/")

    async def on_event(self, event: TelegramEvent, context: RoutingContext) -> None:
        if not isinstance(event, MessageEvent):
            return
        if not event.has_media:
            return
        if context.media_type is None:
            return
        if not event.file_id and not event.file_unique_id:
            return

        if not self._config.evaluate(
            chat_id=event.chat_id,
            user_id=event.user_id,
            media_type=context.media_type,
        ):
            return  # lazy mode — skip eager download

        # Check if already cached
        if event.file_unique_id:
            cached = await self._storage.retrieve(event.bot_id, event.file_unique_id)
            if cached is not None:
                return

        asyncio.create_task(self._download(event, context))

    async def _download(self, event: MessageEvent, context: RoutingContext) -> None:
        file_id = event.file_id
        file_unique_id = event.file_unique_id

        if not file_id:
            logger.warning("eager download skipped: no file_id", bot=event.bot_id)
            return
        if not file_unique_id:
            logger.warning(
                "eager download skipped: no file_unique_id", bot=event.bot_id
            )
            return
        assert context.media_type is not None

        client = self._clients.get(event.bot_id)
        if client is None:
            logger.warning("no client for eager download", bot=event.bot_id)
            return

        if client._client is None:
            logger.warning(
                "client._client is None, cannot eager download",
                bot=event.bot_id,
                file_unique_id=file_unique_id,
            )
            return

        if not client._client.is_connected:
            logger.warning(
                "client disconnected, cannot eager download",
                bot=event.bot_id,
                file_unique_id=file_unique_id,
            )
            return

        try:
            result = await client._client.download_media(file_id, in_memory=True)
        except Exception:
            logger.exception(
                "eager download failed",
                bot=event.bot_id,
                file_unique_id=file_unique_id,
                exc_info=True,
            )
            return

        if result is None:
            logger.warning(
                "eager download returned no data",
                bot=event.bot_id,
                file_unique_id=file_unique_id,
            )
            return

        raw: bytes
        if isinstance(result, (bytes, bytearray)):
            raw = result
        elif hasattr(result, "getvalue"):
            raw = result.getvalue()
        elif hasattr(result, "read"):
            raw = result.read()
        else:
            logger.warning(
                "eager download returned unsupported type",
                bot=event.bot_id,
                file_unique_id=file_unique_id,
                type=type(result).__name__,
            )
            return

        ext = _MEDIA_EXTENSION.get(context.media_type)
        if ext is None:
            raise ValueError(
                f"Unsupported media type: {context.media_type!r}. "
                f"Supported types: {list(_MEDIA_EXTENSION.keys())}"
            )

        await self._storage.store(event.bot_id, file_unique_id, raw, ext)

        logger.info(
            "eager download complete",
            bot=event.bot_id,
            file_unique_id=file_unique_id,
            ext=ext,
            size=len(raw),
        )

        if self._publisher is not None:
            media_url = f"{self._media_base_url}/files/{event.bot_id}/{file_unique_id}"
            ready = MediaReadyEvent(
                file_unique_id=file_unique_id,
                file_id=file_id,
                media_url=media_url,
                original_event_id=event.event_id,
                bot_id=event.bot_id,
            )
            routing_key = f"media.ready.{event.bot_id}.{context.media_type}"
            try:
                await self._publisher.publish(routing_key, ready)
            except Exception as e:
                logger.exception(
                    "failed to publish media_ready event",
                    routing_key=routing_key,
                    exc_info=e,
                )


# No changes needed - all identity/equality checks are correct
