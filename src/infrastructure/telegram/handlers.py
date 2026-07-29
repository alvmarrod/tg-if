from pathlib import Path
from typing import Any

from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from domain.entities import (
    CallbackQueryEvent,
    ChatType,
    CommandEvent,
    EditedCommandEvent,
    EditedMessageEvent,
    MessageEvent,
    MessageReactionCountUpdatedEvent,
    MessageReactionUpdatedEvent,
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
    raw = raw.replace("-", "_")
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


def _extract_reply_to_message(reply: Any) -> dict[str, Any] | None:
    if reply is None:
        return None
    return {
        "message_id": reply.id,
        "from": _extract_from_user(reply.from_user),
        "text": getattr(reply, "text", None),
        "caption": getattr(reply, "caption", None),
    }


def message_to_event(bot_id: str, message: Message) -> MessageEvent | CommandEvent:
    command, args = _detect_command(message.text)

    from_user = _extract_from_user(message.from_user)
    reply_to_message_id = message.reply_to_message_id
    reply_to_message = _extract_reply_to_message(message.reply_to_message)

    if command is not None:
        return CommandEvent(
            event_id=str(message.id),
            bot_id=bot_id,
            chat_id=message.chat.id,
            user_id=message.from_user.id if message.from_user else 0,
            from_user=from_user,
            message_id=message.id,
            reply_to_message_id=reply_to_message_id,
            reply_to_message=reply_to_message,
            command=command,
            command_args=args,
            text=message.text,
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
        reply_to_message=reply_to_message,
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


def edited_message_to_event(
    bot_id: str, message: Message
) -> EditedMessageEvent | EditedCommandEvent:
    command, args = _detect_command(message.text)

    from_user = _extract_from_user(message.from_user)
    reply_to_message_id = message.reply_to_message_id
    reply_to_message = _extract_reply_to_message(message.reply_to_message)

    if command is not None:
        return EditedCommandEvent(
            event_id=str(message.id),
            bot_id=bot_id,
            chat_id=message.chat.id,
            user_id=message.from_user.id if message.from_user else 0,
            from_user=from_user,
            message_id=message.id,
            reply_to_message_id=reply_to_message_id,
            reply_to_message=reply_to_message,
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

    return EditedMessageEvent(
        event_id=str(message.id),
        bot_id=bot_id,
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        from_user=from_user,
        message_id=message.id,
        reply_to_message_id=reply_to_message_id,
        reply_to_message=reply_to_message,
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


def _extract_reaction_emoji(reactions: list[Any]) -> str | None:
    """Extract the first emoji from a Pyrogram Reaction list."""
    if not reactions:
        return None
    r = reactions[0]
    return getattr(r, "emoji", None)


def reaction_updated_to_event(
    bot_id: str, reaction: Any
) -> MessageReactionUpdatedEvent:
    from_user = _extract_from_user(getattr(reaction, "from_user", None))

    new_reaction = getattr(reaction, "new_reaction", [])
    old_reaction = getattr(reaction, "old_reaction", [])

    return MessageReactionUpdatedEvent(
        event_id=f"ru_{reaction.message_id}_{getattr(reaction, 'date', 0)}",
        bot_id=bot_id,
        chat_id=reaction.chat.id if reaction.chat else 0,
        user_id=int(from_user["id"]) if from_user else 0,
        from_user=from_user,
        message_id=reaction.message_id,
        reaction_emoji=_extract_reaction_emoji(new_reaction) or "",
        old_reaction_emoji=_extract_reaction_emoji(old_reaction),
        raw_payload={},
        update_type="message_reaction_updated",
    )


def context_from_reaction_updated(reaction: Any) -> RoutingContext:
    new_reaction = getattr(reaction, "new_reaction", [])
    old_reaction = getattr(reaction, "old_reaction", [])
    return RoutingContext(
        chat_type=ChatType(
            reaction.chat.type.value
            if reaction.chat and reaction.chat.type
            else "private"
        ),
        reaction_emoji=_extract_reaction_emoji(new_reaction) or None,
        old_reaction_emoji=_extract_reaction_emoji(old_reaction) or None,
    )


def reaction_count_updated_to_event(
    bot_id: str, reaction: Any
) -> MessageReactionCountUpdatedEvent:
    from_user = _extract_from_user(getattr(reaction, "from_user", None))
    raw_reactions = getattr(reaction, "reactions", [])
    reactions_list = [
        {
            "emoji": getattr(r, "emoji", None),
            "count": getattr(r, "count", None),
        }
        for r in raw_reactions
    ]

    return MessageReactionCountUpdatedEvent(
        event_id=f"rc_{reaction.message_id}_{getattr(reaction, 'date', 0)}",
        bot_id=bot_id,
        chat_id=reaction.chat.id if reaction.chat else 0,
        user_id=int(from_user["id"]) if from_user else 0,
        from_user=from_user,
        message_id=reaction.message_id,
        reactions=reactions_list,
        raw_payload={},
        update_type="message_reaction_count_updated",
    )


def callback_to_event(bot_id: str, query: CallbackQuery) -> CallbackQueryEvent:
    from_user = _extract_from_user(query.from_user)

    if isinstance(query.data, bytes):
        callback_data = query.data.decode()
    elif isinstance(query.data, str):
        callback_data = query.data
    else:
        raise TypeError(f"Unexpected callback_data type: {type(query.data)}")

    return CallbackQueryEvent(
        event_id=str(query.id),
        bot_id=bot_id,
        chat_id=query.message.chat.id if query.message and query.message.chat else 0,
        user_id=int(from_user["id"]) if from_user else 0,
        from_user=from_user,
        callback_id=str(query.id),
        callback_data=callback_data,
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
    command, _ = _detect_command(getattr(message, "text", None))

    media_type = str(message.media.value) if message.media is not None else None

    return RoutingContext(
        chat_type=ChatType(chat_type_str),
        has_media=message.media is not None,
        media_type=media_type,
        command=command,
        is_reply=message.reply_to_message_id is not None,
        is_forward=message.forward_origin is not None,
    )


def build_reply_markup(
    buttons: list[list[dict[str, Any]]] | None,
) -> InlineKeyboardMarkup:
    if not buttons:
        raise ValueError("build_reply_markup requires non-empty buttons list")

    rows: list[list[InlineKeyboardButton]] = []
    for row in buttons:
        keyboard_row: list[InlineKeyboardButton] = []
        for btn in row:
            # Validate button has at least one type
            has_web_app = "web_app" in btn
            has_callback = "callback_data" in btn
            has_url = "url" in btn

            if not (has_web_app or has_callback or has_url):
                raise ValueError(
                    f"Button must have 'web_app', 'callback_data', or 'url': {btn}"
                )

            if has_web_app:
                web_app_data = btn.get("web_app")
                if web_app_data is None:
                    raise ValueError("web_app button requires 'web_app' field")
                web_app_url = web_app_data.get("url")
                if web_app_url is None or web_app_url == "":
                    raise ValueError("web_app button requires non-empty 'url'")
                keyboard_row.append(
                    InlineKeyboardButton(
                        text=btn["text"],
                        web_app=WebAppInfo(url=web_app_url),
                    )
                )
            elif has_callback:
                keyboard_row.append(
                    InlineKeyboardButton(
                        text=btn["text"],
                        callback_data=btn.get("callback_data") or "",
                    )
                )
            else:
                keyboard_row.append(
                    InlineKeyboardButton(
                        text=btn["text"],
                        url=btn.get("url") or "",
                    )
                )
        rows.append(keyboard_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def parse_session_path(session_file: str) -> tuple[str, str]:
    p = Path(session_file)
    return p.stem, str(p.parent)
