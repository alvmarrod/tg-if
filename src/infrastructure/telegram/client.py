from collections.abc import Awaitable, Callable
from typing import Any, cast

import pyrogram
import pyrogram.connection.connection  # noqa: F811
import pyrogram.session.session  # noqa: F811
import structlog
from pyrogram.client import Client as PyrogramClient
from pyrogram.enums import ParseMode
from pyrogram.handlers.disconnect_handler import DisconnectHandler
from pyrogram.types import BotCommand, InputMediaPhoto, InputMediaVideo, Message

from domain.entities import ChatType, RoutingContext, TelegramEvent
from infrastructure.config import BotConfig
from infrastructure.telegram.handlers import (
    build_reply_markup,
    callback_to_event,
    context_from_callback,
    context_from_reaction_updated,
    edited_message_to_event,
    extract_routing_context,
    message_to_event,
    parse_session_path,
    reaction_count_updated_to_event,
    reaction_updated_to_event,
)

# Increase Pyrogram keepalive tolerance to reduce spurious disconnections.
pyrogram.session.session.Session.PING_INTERVAL = 15  # 5s → 15s
pyrogram.session.session.Session.WAIT_TIMEOUT = 30  # 15s → 30s
pyrogram.connection.connection.Connection.MAX_RETRIES = 5  # 3 → 5


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
        self._bot_token = config.bot_token
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
        self._client = PyrogramClient(**kwargs)
        self._client.on_message()(self._on_message)
        self._client.on_edited_message()(self._on_edited_message)
        self._client.on_callback_query()(self._on_callback_query)
        self._client.on_message_reaction_updated()(self._on_message_reaction_updated)
        self._client.on_message_reaction_count_updated()(
            self._on_message_reaction_count_updated
        )
        self._client.add_handler(DisconnectHandler(self._on_disconnect_handler))
        self._known_chats: dict[int, dict[str, Any]] = {}

    @property
    def bot_id(self) -> str:
        return self._bot_id

    @property
    def is_user(self) -> bool:
        return self._bot_token is None

    @property
    def known_chats(self) -> list[dict[str, Any]]:
        """Return lightweight dicts of chats seen by this client."""
        return list(self._known_chats.values())

    def _register_chat(self, chat: Any) -> None:
        """Store or update a chat entry from a raw Pyrogram Chat object."""
        title = chat.title or ""
        if not title:
            first = getattr(chat, "first_name", "") or ""
            last = getattr(chat, "last_name", "") or ""
            title = f"{first} {last}".strip()
        self._known_chats[chat.id] = {
            "chat_id": chat.id,
            "title": title,
            "type": str(chat.type).split(".")[-1].lower() if chat.type else "unknown",
            "members": getattr(chat, "member_count", 0) or 0,
            "can_read": True,
            "can_write": getattr(
                getattr(chat, "permissions", None), "can_send_messages", False
            ),
        }

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
        **kwargs: Any,
    ) -> Message:
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
        **kwargs: Any,
    ) -> Message:
        kwargs["photo"] = photo
        kwargs["caption"] = caption
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
        **kwargs: Any,
    ) -> Message:
        kwargs["document"] = document
        kwargs["caption"] = caption
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
        **kwargs: Any,
    ) -> Message:
        kwargs["video"] = video
        kwargs["caption"] = caption
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
        **kwargs: Any,
    ) -> Message:
        kwargs["audio"] = audio
        kwargs["caption"] = caption
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
        **kwargs: Any,
    ) -> Message:
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
        **kwargs: Any,
    ) -> bool:
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
        **kwargs: Any,
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
        kwargs["media"] = converted
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

    async def _on_disconnect_handler(self, client: PyrogramClient) -> None:
        logger.warning("telegram client disconnected", bot=self._bot_id)
        if self._on_disconnect_cb:
            await self._on_disconnect_cb()

    async def _on_message(self, client: PyrogramClient, message: Message) -> None:
        if self._event_callback is None:
            return
        self._register_chat(message.chat)
        event = message_to_event(self._bot_id, message)
        event.update_type = "message"
        context = extract_routing_context(message)
        await self._event_callback(event, context)

    async def _on_callback_query(self, client: PyrogramClient, query: Any) -> None:
        if self._event_callback is None:
            return
        chat = getattr(query, "message", None) and getattr(query.message, "chat", None)
        if chat:
            self._register_chat(chat)
        event = callback_to_event(self._bot_id, query)
        event.update_type = "callback_query"
        context = context_from_callback(query)
        await self._event_callback(event, context)

    async def _on_edited_message(
        self, client: PyrogramClient, message: Message
    ) -> None:
        if self._event_callback is None:
            return
        self._register_chat(message.chat)
        event = edited_message_to_event(self._bot_id, message)
        event.update_type = "edited_message"
        context = extract_routing_context(message)
        await self._event_callback(event, context)

    async def _on_message_reaction_updated(
        self, client: PyrogramClient, reaction: Any
    ) -> None:
        if self._event_callback is None:
            return
        chat = getattr(reaction, "chat", None)
        if chat:
            self._register_chat(chat)
        event = reaction_updated_to_event(self._bot_id, reaction)
        context = context_from_reaction_updated(reaction)
        await self._event_callback(event, context)

    async def _on_message_reaction_count_updated(
        self, client: PyrogramClient, reaction: Any
    ) -> None:
        if self._event_callback is None:
            return
        chat = getattr(reaction, "chat", None)
        if chat:
            self._register_chat(chat)
        event = reaction_count_updated_to_event(self._bot_id, reaction)
        context = RoutingContext(chat_type=ChatType.PRIVATE)
        await self._event_callback(event, context)

    async def get_dialogs(self) -> list[dict[str, Any]]:
        """Return known chats.

        This method only works for user (non-bot) accounts in Pyrogram.
        For bot accounts, chats are tracked locally via _register_chat()
        as they appear in incoming events. Use the known_chats property
        instead for a full list.
        """
        return self.known_chats

    async def discover_chats(self) -> list[dict[str, Any]]:
        """Call Pyrogram's real get_dialogs() to discover all accessible chats.

        Only works for user (non-bot) accounts via MTProto.
        Bots will get BOT_METHOD_INVALID — callers must guard with is_user.
        """
        dialogs: list[dict[str, Any]] = []
        gen = self._client.get_dialogs()
        if gen is None:
            return dialogs
        async for dialog in gen:
            chat = dialog.chat
            permissions = getattr(chat, "permissions", None)
            title = chat.title or ""
            if not title:
                first = getattr(chat, "first_name", "") or ""
                last = getattr(chat, "last_name", "") or ""
                title = f"{first} {last}".strip()
            dialogs.append(
                {
                    "chat_id": chat.id,
                    "title": title,
                    "type": str(chat.type).split(".")[-1].lower()
                    if chat.type
                    else "unknown",
                    "members": getattr(chat, "member_count", 0) or 0,
                    "can_read": True,
                    "can_write": permissions.can_send_messages
                    if permissions
                    else False,
                }
            )
        return dialogs

    async def get_chat_history(
        self,
        chat_id: int,
        limit: int = 0,
        offset_id: int = 0,
        offset_date: Any = None,
    ) -> list[Any]:
        """Fetch chat history messages.

        Returns a list of Pyrogram Message objects (already iterated).
        When limit=0 returns up to Telegram's max per-page (typically 100).
        For full history the caller must paginate.
        """
        messages: list[Any] = []
        kwargs: dict[str, Any] = dict(
            chat_id=chat_id,
            limit=limit,
            offset_id=offset_id,
        )
        if offset_date is not None:
            kwargs["offset_date"] = offset_date
        gen = self._client.get_chat_history(**kwargs)
        if gen is not None:
            async for msg in gen:
                messages.append(msg)
        return messages

    async def download_media(
        self,
        message: Any,
        file_path: str,
    ) -> str | None:
        """Download media from a message to disk.

        Returns the local file path, or None on failure.
        """
        result = await self._client.download_media(
            message=message,
            file_name=file_path,
        )
        if result is None:
            return None
        if isinstance(result, str):
            return result
        return None
