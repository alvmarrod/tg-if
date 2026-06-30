from pathlib import Path
from typing import Any

from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from domain.entities import (
    CallbackQueryEvent,
    ChatType,
    CommandEvent,
    MessageEvent,
    RoutingContext,
)


_MEDIA_ATTRS = [
    "photo",
    "video",
    "audio",
    "document",
    "animation",
    "voice",
    "video_note",
    "sticker",
]

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


def _extract_media_info(
    message: Message,
) -> tuple[str | None, str | None, dict[str, Any]]:
    for attr in _MEDIA_ATTRS:
        media_obj = getattr(message, attr, None)
        if media_obj is None:
            continue
        file_id: str | None = getattr(media_obj, "file_id", None)
        file_unique_id: str | None = getattr(media_obj, "file_unique_id", None)
        raw: dict[str, Any] = {
            "file_id": file_id,
            "file_unique_id": file_unique_id,
        }
        for field in (
            "file_size",
            "mime_type",
            "width",
            "height",
            "duration",
            "title",
            "performer",
            "file_name",
            "emoji",
        ):
            val = getattr(media_obj, field, None)
            if val is not None:
                raw[field] = val
        return file_id, file_unique_id, raw
    return None, None, {}


def _detect_command(text: str | None) -> tuple[str | None, list[str]]:
    if not text or not text.startswith("/"):
        return None, []
    parts = text.split()
    raw = parts[0].lstrip("/").split("@")[0]
    return raw, parts[1:]


def _extract_from_user(
    user: Any,
) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "is_bot": user.is_bot,
        "first_name": user.first_name,
        "last_name": getattr(user, "last_name", None),
        "username": getattr(user, "username", None),
        "language_code": getattr(user, "language_code", None),
    }


def message_to_event(bot_id: str, message: Message) -> MessageEvent | CommandEvent:
    command, args = _detect_command(message.text)

    from_user = _extract_from_user(message.from_user)
    reply_to_message_id = message.reply_to_message_id

    if command is not None:
        return CommandEvent(
            event_id=str(message.id),
            bot_id=bot_id,
            chat_id=message.chat.id,
            user_id=message.from_user.id if message.from_user else 0,
            from_user=from_user,
            message_id=message.id,
            reply_to_message_id=reply_to_message_id,
            command=command,
            command_args=args,
            text=message.text or "",
            raw_payload={},
        )

    has_media = message.media is not None
    media_type = str(message.media.value) if message.media else None

    file_id, file_unique_id, media_raw = (
        _extract_media_info(message) if has_media else (None, None, {})
    )
    is_reply = reply_to_message_id is not None
    is_forward = message.forward_origin is not None

    return MessageEvent(
        event_id=str(message.id),
        bot_id=bot_id,
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        from_user=from_user,
        message_id=message.id,
        reply_to_message_id=reply_to_message_id,
        text=message.text,
        caption=message.caption,
        has_media=has_media,
        media_type=media_type,
        file_id=file_id,
        file_unique_id=file_unique_id,
        raw_payload=media_raw,
        is_reply=is_reply,
        is_forward=is_forward,
    )


def callback_to_event(bot_id: str, query: CallbackQuery) -> CallbackQueryEvent:
    from_user = _extract_from_user(query.from_user)

    return CallbackQueryEvent(
        event_id=str(query.id),
        bot_id=bot_id,
        chat_id=query.message.chat.id if query.message else 0,
        user_id=query.from_user.id,
        from_user=from_user,
        callback_id=str(query.id),
        callback_data=query.data.decode()
        if isinstance(query.data, bytes)
        else query.data or "",
        message_id=query.message.id if query.message else None,
        raw_payload={},
    )


def context_from_callback(query: CallbackQuery) -> RoutingContext:
    chat_type_str = (
        query.message.chat.type.value
        if query.message and query.message.chat and query.message.chat.type
        else "private"
    )
    return RoutingContext(chat_type=ChatType(chat_type_str))


def extract_routing_context(message: Message) -> RoutingContext:
    chat_type_str = (
        message.chat.type.value if message.chat and message.chat.type else "private"
    )
    command, _ = _detect_command(message.text)

    return RoutingContext(
        chat_type=ChatType(chat_type_str),
        has_media=message.media is not None,
        media_type=str(message.media.value) if message.media else None,
        command=command,
        is_reply=message.reply_to_message_id is not None,
        is_forward=message.forward_origin is not None,
    )


def build_reply_markup(
    buttons: list[list[dict[str, str]]] | None,
) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for row in buttons:
        keyboard_row = [
            InlineKeyboardButton(
                text=btn["text"], callback_data=btn.get("callback_data") or ""
            )
            if "callback_data" in btn
            else InlineKeyboardButton(text=btn["text"], url=btn.get("url") or "")
            for btn in row
        ]
        rows.append(keyboard_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)  # type: ignore[arg-type]


def parse_session_path(session_file: str) -> tuple[str, str]:
    p = Path(session_file)
    return p.stem, str(p.parent)
