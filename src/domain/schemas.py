from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, TypedDict


class FromUser(TypedDict, total=False):
    id: int
    is_bot: bool
    first_name: str
    last_name: str | None
    username: str | None
    language_code: str | None


class ReplyToMessage(TypedDict, total=False):
    message_id: int
    from_: FromUser | None
    text: str | None
    caption: str | None


class ChatDialog(TypedDict, total=False):
    chat_id: int
    title: str
    type: str
    members: int
    can_read: bool
    can_write: bool


class EventEnvelope(TypedDict, total=False):
    event_id: str
    timestamp: float
    bot_id: str
    event_type: str
    event_subtype: str | None
    chat_id: int
    user_id: int
    message_id: int | None
    text: str | None
    caption: str | None
    command_args: list[str] | None
    from_user: FromUser | None
    reply_to_message_id: int | None
    reply_to_message: ReplyToMessage | None
    routing_context: dict[str, Any]
    payload: Any
    file_id: str | None
    file_unique_id: str | None
    media_status: str | None
    media_url: str | None
    callback_id: str | None
    callback_data: str | None
    reaction_emoji: str | None
    old_reaction_emoji: str | None
    reactions: list[dict[str, Any]] | None


class MediaRawInfo(TypedDict, total=False):
    file_id: str | None
    file_unique_id: str | None
    file_size: int | None
    mime_type: str | None
    width: int | None
    height: int | None
    duration: int | None
    title: str | None
    performer: str | None
    file_name: str | None
    emoji: str | None


@dataclass
class FileInfo:
    bot_id: str
    file_unique_id: str
    ext: str
    size: int
    accesses: int
    last_access: datetime | None
    stored_at: datetime


@dataclass
class UploadEntry:
    content_hash: str
    bot_id: str
    url_hash: str | None = None
    url: str | None = None
    file_id: str | None = None
    file_unique_id: str | None = None
    ext: str = "bin"
    size: int = 0
    created_at: float = 0.0
    last_used_at: float = 0.0
    use_count: int = 0


class AdminSignalType(str, Enum):
    RESPONSE_FAILED = "response_failed"
    COMPONENT_CONNECTED = "component_connected"
    COMPONENT_DISCONNECTED = "component_disconnected"
    CONFIG_WARNING = "config_warning"
