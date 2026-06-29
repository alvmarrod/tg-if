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
        if not event.has_media or not event.file_id or not event.file_unique_id:
            return
        if not context.media_type:
            return

        if not self._config.evaluate(
            chat_id=event.chat_id,
            user_id=event.user_id,
            media_type=context.media_type,
        ):
            return  # lazy mode — skip eager download

        # Check if already cached
        cached = await self._storage.retrieve(event.bot_id, event.file_unique_id)
        if cached is not None:
            return

        asyncio.create_task(self._download(event))

    async def _download(self, event: MessageEvent) -> None:
        file_id = event.file_id
        file_unique_id = event.file_unique_id
        if not file_id or not file_unique_id:
            return

        client = self._clients.get(event.bot_id)
        if client is None:
            logger.warning("no client for eager download", bot=event.bot_id)
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
        except Exception as exc:
            logger.warning(
                "eager download failed",
                bot=event.bot_id,
                file_unique_id=file_unique_id,
                error=str(exc),
            )
            return

        if result is None:
            logger.warning(
                "eager download returned no data",
                bot=event.bot_id,
                file_unique_id=file_unique_id,
            )
            return

        raw: bytes = result.getvalue() if hasattr(result, "getvalue") else result.read()  # type: ignore[union-attr]

        ext = _MEDIA_EXTENSION.get(event.media_type or "", "bin")

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
            routing_key = f"media.ready.{event.bot_id}.{event.media_type or 'unknown'}"
            try:
                await self._publisher.publish(routing_key, ready)
            except Exception:
                logger.exception(
                    "failed to publish media_ready event",
                    routing_key=routing_key,
                )
