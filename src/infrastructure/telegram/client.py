from collections.abc import Awaitable, Callable
from typing import Any, cast

import pyrogram
import structlog
from pyrogram.enums import ParseMode
from pyrogram.handlers import DisconnectHandler
from pyrogram.types import BotCommand, InputMediaPhoto, InputMediaVideo, Message

from domain.entities import RoutingContext, TelegramEvent
from infrastructure.config import BotConfig
from infrastructure.telegram.handlers import (
    build_reply_markup,
    callback_to_event,
    context_from_callback,
    extract_routing_context,
    message_to_event,
    parse_session_path,
)


logger = structlog.get_logger()

EventCallback = Callable[[TelegramEvent, RoutingContext], Awaitable[None]]


def _parse_mode(value: str | None) -> ParseMode | None:
    if value is None:
        return None
    return ParseMode(value.upper())


class TelegramClient:
    def __init__(
        self,
        config: BotConfig,
        event_callback: EventCallback | None = None,
        on_connect: Callable[[], Awaitable[None]] | None = None,
        on_disconnect: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._bot_id = config.name
        self._event_callback = event_callback
        self._on_connect_cb = on_connect
        self._on_disconnect_cb = on_disconnect
        name, workdir = parse_session_path(config.session_file)
        kwargs: dict[str, Any] = dict(
            name=name,
            api_id=config.api_id,
            api_hash=config.api_hash,
            workdir=workdir,
        )
        if config.bot_token is not None:
            kwargs["bot_token"] = config.bot_token
        self._client = pyrogram.Client(**kwargs)
        self._client.on_message()(self._on_message)
        self._client.on_callback_query()(self._on_callback_query)
        self._client.add_handler(DisconnectHandler(self._on_disconnect_handler))

    @property
    def bot_id(self) -> str:
        return self._bot_id

    async def start(self) -> None:
        try:
            await self._client.start()
            await self._on_connect_handler()
        except Exception:
            logger.warning(
                "telegram client failed to start", bot=self._bot_id, exc_info=True
            )

    async def stop(self) -> None:
        try:
            await self._client.stop()
            logger.info("telegram client stopped", bot=self._bot_id)
        except Exception:
            logger.warning(
                "telegram client stop error", bot=self._bot_id, exc_info=True
            )

    def set_event_callback(self, callback: EventCallback) -> None:
        self._event_callback = callback

    async def set_bot_commands(self, commands: list[tuple[str, str]]) -> None:
        try:
            bot_commands = [
                BotCommand(command=cmd, description=desc) for cmd, desc in commands
            ]
            await self._client.set_bot_commands(bot_commands)
            logger.info("bot commands registered", bot=self._bot_id)
        except Exception:
            logger.warning(
                "bot commands registration failed", bot=self._bot_id, exc_info=True
            )

    async def health(self) -> bool:
        return self._client.is_connected if self._client else False

    async def send_text(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: list[list[dict[str, str]]] | None = None,
    ) -> Message:
        kwargs: dict[str, Any] = {}
        if parse_mode is not None:
            kwargs["parse_mode"] = _parse_mode(parse_mode)
        if reply_to_message_id is not None:
            kwargs["reply_to_message_id"] = reply_to_message_id
        markup = build_reply_markup(reply_markup)
        if markup is not None:
            kwargs["reply_markup"] = markup
        result = await self._client.send_message(chat_id=chat_id, text=text, **kwargs)
        assert result is not None
        return result

    async def send_photo(
        self,
        chat_id: int,
        photo: str,
        caption: str = "",
        parse_mode: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: list[list[dict[str, str]]] | None = None,
    ) -> Message:
        kwargs: dict[str, Any] = dict(photo=photo, caption=caption)
        if parse_mode is not None:
            kwargs["parse_mode"] = _parse_mode(parse_mode)
        if reply_to_message_id is not None:
            kwargs["reply_to_message_id"] = reply_to_message_id
        markup = build_reply_markup(reply_markup)
        if markup is not None:
            kwargs["reply_markup"] = markup
        result = await self._client.send_photo(chat_id=chat_id, **kwargs)
        assert result is not None
        return result

    async def send_document(
        self,
        chat_id: int,
        document: str,
        caption: str = "",
        parse_mode: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: list[list[dict[str, str]]] | None = None,
    ) -> Message:
        kwargs: dict[str, Any] = dict(document=document, caption=caption)
        if parse_mode is not None:
            kwargs["parse_mode"] = _parse_mode(parse_mode)
        if reply_to_message_id is not None:
            kwargs["reply_to_message_id"] = reply_to_message_id
        markup = build_reply_markup(reply_markup)
        if markup is not None:
            kwargs["reply_markup"] = markup
        result = await self._client.send_document(chat_id=chat_id, **kwargs)
        assert result is not None
        return result

    async def send_video(
        self,
        chat_id: int,
        video: str,
        caption: str = "",
        parse_mode: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: list[list[dict[str, str]]] | None = None,
    ) -> Message:
        kwargs: dict[str, Any] = dict(video=video, caption=caption)
        if parse_mode is not None:
            kwargs["parse_mode"] = _parse_mode(parse_mode)
        if reply_to_message_id is not None:
            kwargs["reply_to_message_id"] = reply_to_message_id
        markup = build_reply_markup(reply_markup)
        if markup is not None:
            kwargs["reply_markup"] = markup
        result = await self._client.send_video(chat_id=chat_id, **kwargs)
        assert result is not None
        return result

    async def send_audio(
        self,
        chat_id: int,
        audio: str,
        caption: str = "",
        parse_mode: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: list[list[dict[str, str]]] | None = None,
    ) -> Message:
        kwargs: dict[str, Any] = dict(audio=audio, caption=caption)
        if parse_mode is not None:
            kwargs["parse_mode"] = _parse_mode(parse_mode)
        if reply_to_message_id is not None:
            kwargs["reply_to_message_id"] = reply_to_message_id
        markup = build_reply_markup(reply_markup)
        if markup is not None:
            kwargs["reply_markup"] = markup
        result = await self._client.send_audio(chat_id=chat_id, **kwargs)
        assert result is not None
        return result

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: list[list[dict[str, str]]] | None = None,
    ) -> Message:
        kwargs: dict[str, Any] = {}
        if parse_mode is not None:
            kwargs["parse_mode"] = _parse_mode(parse_mode)
        markup = build_reply_markup(reply_markup)
        if markup is not None:
            kwargs["reply_markup"] = markup
        result = await self._client.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, **kwargs
        )
        assert result is not None
        return result

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
        url: str | None = None,
        cache_time: int = 0,
    ) -> bool:
        kwargs: dict[str, Any] = {}
        if text is not None:
            kwargs["text"] = text
        if url is not None:
            kwargs["url"] = url
        result = await self._client.answer_callback_query(
            callback_query_id=callback_query_id,
            show_alert=show_alert,
            cache_time=cache_time,
            **kwargs,
        )
        return cast(bool, result)

    async def send_media_group(
        self,
        chat_id: int,
        media: list[dict[str, Any]],
        reply_to_message_id: int | None = None,
    ) -> list[Message]:
        converted: list[InputMediaPhoto | InputMediaVideo] = []
        for item in media:
            t = item.get("type")
            m = item.get("media", "")
            cap = item.get("caption", "")
            if t == "photo":
                converted.append(InputMediaPhoto(media=m, caption=cap))
            elif t == "video":
                converted.append(InputMediaVideo(media=m, caption=cap))
        if not converted:
            return []
        kwargs: dict[str, Any] = dict(media=converted)
        if reply_to_message_id is not None:
            kwargs["reply_to_message_id"] = reply_to_message_id
        return await self._client.send_media_group(chat_id=chat_id, **kwargs)

    async def delete_message(
        self,
        chat_id: int,
        message_ids: int | list[int],
    ) -> int:
        return await self._client.delete_messages(
            chat_id=chat_id, message_ids=message_ids
        )

    async def _on_connect_handler(self) -> None:
        logger.info("telegram client connected", bot=self._bot_id)
        if self._on_connect_cb:
            await self._on_connect_cb()

    async def _on_disconnect_handler(self, client: pyrogram.Client) -> None:
        logger.warning("telegram client disconnected", bot=self._bot_id)
        if self._on_disconnect_cb:
            await self._on_disconnect_cb()

    async def _on_message(self, client: pyrogram.Client, message: Message) -> None:
        if self._event_callback is None:
            return
        event = message_to_event(self._bot_id, message)
        context = extract_routing_context(message)
        await self._event_callback(event, context)

    async def _on_callback_query(self, client: pyrogram.Client, query: Any) -> None:
        if self._event_callback is None:
            return
        event = callback_to_event(self._bot_id, query)
        context = context_from_callback(query)
        await self._event_callback(event, context)
