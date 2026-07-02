"""Domain entities for tg-if service."""

from enum import Enum
from typing import Optional, Any, Literal
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    """Type of Telegram event."""

    MESSAGE = "message"
    COMMAND = "command"
    CALLBACK_QUERY = "callback_query"
    INLINE_QUERY = "inline_query"
    EDITED_MESSAGE = "edited_message"
    MESSAGE_REACTION_UPDATED = "message_reaction_updated"
    MESSAGE_REACTION_COUNT_UPDATED = "message_reaction_count_updated"


class ChatType(str, Enum):
    """Type of Telegram chat. Mirrors Pyrofork's ChatType enum."""

    PRIVATE = "private"
    BOT = "bot"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"
    FORUM = "forum"
    MONOFORUM = "monoforum"


class RoutingContext(BaseModel):
    """Metadata extracted from events for routing decisions."""

    chat_type: ChatType
    has_media: bool = False
    media_type: Optional[str] = None  # photo, video, document, audio, etc.
    user_role: Optional[str] = None  # creator, administrator, member
    command: Optional[str] = None  # e.g., "/start", "/help"
    is_reply: bool = False
    is_forward: bool = False
    reaction_emoji: Optional[str] = None  # emoji for reaction events
    old_reaction_emoji: Optional[str] = None  # previous emoji for reaction changes

    model_config = ConfigDict(use_enum_values=True)


class TelegramEvent(BaseModel):
    """Base Telegram event (abstract)."""

    event_id: str = Field(..., description="Unique event identifier")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    bot_id: str = Field(..., description="Bot identifier")
    event_type: EventType
    chat_id: int
    user_id: int
    from_user: dict[str, Any] | None = Field(
        default=None,
        description="Sender info: id, first_name, last_name, username, is_bot, language_code",
    )
    raw_payload: dict[str, Any] = Field(
        default_factory=dict, description="Raw Telegram update"
    )
    update_type: str | None = Field(
        default=None,
        description="Pyrofork handler source: message, edited_message, callback_query, message_reaction_updated, etc.",
    )

    model_config = ConfigDict(use_enum_values=True)


class MessageEvent(TelegramEvent):
    """Message-specific event (text, media messages)."""

    event_type: EventType = EventType.MESSAGE
    message_id: int
    text: Optional[str] = None
    caption: Optional[str] = None
    media_type: Optional[str] = None
    has_media: bool = False
    is_reply: bool = False
    reply_to_message_id: int | None = None
    is_forward: bool = False
    file_id: Optional[str] = Field(
        default=None, description="Telegram file_id (session-specific, can download)"
    )
    file_unique_id: Optional[str] = Field(
        default=None,
        description="Telegram file_unique_id (permanent, content-based dedup key)",
    )
    media_status: str = Field(
        default="pending",
        description='Media availability: "pending" or "ready"',
    )
    media_url: Optional[str] = Field(
        default=None,
        description="URL to fetch the media via tg-if HTTP proxy",
    )


class CommandEvent(TelegramEvent):
    """Command event (/start, /help, etc.)."""

    event_type: EventType = EventType.COMMAND
    message_id: int
    reply_to_message_id: int | None = None
    command: str = Field(..., description="Command without slash, e.g., 'start'")
    command_args: list[str] = Field(
        default_factory=list, description="Arguments after command"
    )
    text: str = Field(..., description="Full message text")


class CallbackQueryEvent(TelegramEvent):
    """Inline button callback event."""

    event_type: EventType = EventType.CALLBACK_QUERY
    callback_id: str = Field(..., description="Telegram callback query ID")
    callback_data: str = Field(..., description="Data attached to button")
    message_id: Optional[int] = None


class EditedMessageEvent(TelegramEvent):
    """Edited message event (text or media was edited)."""

    event_type: EventType = EventType.EDITED_MESSAGE
    message_id: int
    text: Optional[str] = None
    caption: Optional[str] = None
    media_type: Optional[str] = None
    has_media: bool = False
    is_reply: bool = False
    reply_to_message_id: int | None = None
    is_forward: bool = False
    file_id: Optional[str] = Field(
        default=None, description="Telegram file_id (session-specific, can download)"
    )
    file_unique_id: Optional[str] = Field(
        default=None,
        description="Telegram file_unique_id (permanent, content-based dedup key)",
    )
    media_status: str = Field(
        default="pending",
        description='Media availability: "pending" or "ready"',
    )
    media_url: Optional[str] = Field(
        default=None,
        description="URL to fetch the media via tg-if HTTP proxy",
    )


class EditedCommandEvent(TelegramEvent):
    """Edited command event (a command message was edited)."""

    event_type: EventType = EventType.EDITED_MESSAGE
    message_id: int
    reply_to_message_id: int | None = None
    command: str = Field(..., description="Command without slash, e.g., 'start'")
    command_args: list[str] = Field(
        default_factory=list, description="Arguments after command"
    )
    text: str = Field(..., description="Full message text")


class MessageReactionUpdatedEvent(TelegramEvent):
    """Per-user reaction change on a bot message."""

    event_type: EventType = EventType.MESSAGE_REACTION_UPDATED
    message_id: int
    reaction_emoji: str = Field(..., description="The new reaction emoji")
    old_reaction_emoji: str | None = Field(
        default=None, description="Previous reaction emoji, None if first reaction"
    )


class MessageReactionCountUpdatedEvent(TelegramEvent):
    """Aggregate anonymous reaction count change."""

    event_type: EventType = EventType.MESSAGE_REACTION_COUNT_UPDATED
    message_id: int
    reactions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of {emoji, count} dicts for all reactions on the message",
    )


class MediaScope(str, Enum):
    """Scope for media config rules."""

    GLOBAL = "global"
    CHAT = "chat"
    USER = "user"


class MediaConfigRule(BaseModel):
    """Rule controlling eager/lazy media download behavior."""

    scope: MediaScope
    scope_id: Optional[str] = Field(
        default=None, description="chat_id or user_id; None for global"
    )
    content_types: list[str] = Field(
        default_factory=lambda: ["all"],
        description="Media types this rule applies to, or ['all']",
    )
    action: str = Field(..., description='"eager" or "lazy"')

    model_config = ConfigDict(use_enum_values=True)


class MediaReadyEvent(BaseModel):
    """Published when eager download completes and media is cached."""

    file_unique_id: str
    file_id: str
    media_url: str
    original_event_id: str
    bot_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(use_enum_values=True)


class OutgoingResponse(BaseModel):
    """Response sent by a subscriber to be delivered to Telegram."""

    response_id: str = Field(..., description="Unique response identifier")
    correlation_id: str = Field(..., description="Correlates to original event")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    bot_id: str = Field(..., description="Bot to send from")
    chat_id: int
    response_type: str = Field(
        ...,
        description="send method: text, photo, document, video, audio, media_group, edit_message_text, answer_callback_query, delete_message",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict, description="kwargs forwarded to the send method"
    )
    reply_to: str | None = Field(
        default=None,
        description="Queue name for delivery result notification",
    )


class OutgoingResponseResult(BaseModel):
    """Delivery result sent back to subscriber when reply_to is provided."""

    response_id: str
    correlation_id: str
    bot_id: str
    chat_id: int
    message_id: int | None = None
    status: Literal["delivered", "failed"]
    error_type: str | None = None
    error_message: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BotCommandRegistration(BaseModel):
    """A subscriber's bot command registration for a specific bot."""

    subscriber_id: str = Field(..., description="Unique subscriber identifier")
    commands: list[dict[str, str]] = Field(
        ..., description="List of {command, description} dicts"
    )


class SubscriberCommandEnvelope(BaseModel):
    """Message published by a subscriber to register/deregister bot commands."""

    action: Literal["register", "deregister"]
    bot_id: str
    subscriber_id: str
    reply_to: str | None = Field(
        default=None,
        description="Queue name to publish the response to",
    )
    commands: list[dict[str, str]] = Field(
        default_factory=list,
        description="List of {command, description} dicts (required for register)",
    )


class SubscriberCommandResponse(BaseModel):
    """Response published back to the subscriber."""

    status: Literal["ok", "nok"]
    registered: list[str] = Field(
        default_factory=list, description="Commands that were registered"
    )
    conflicts: list[str] = Field(
        default_factory=list,
        description="Conflict details if status is nok",
    )


class ExportState(str, Enum):
    """State of a chat export operation."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class ExportProgress(BaseModel):
    """Progress tracking for a running export."""

    total: int = 0
    processed: int = 0
    state: ExportState = ExportState.IDLE
    media_count: int = 0
    media_bytes: int = 0
    current_chat_id: int | None = None
    start_time: datetime | None = None

    model_config = ConfigDict(use_enum_values=True)

    @property
    def pct(self) -> float:
        if self.total == 0:
            return 0.0
        return round(self.processed / self.total * 100, 1)


class ChatInfo(BaseModel):
    """Information about a chat for the /chats command."""

    chat_id: int
    title: str
    chat_type: ChatType
    members: int = 0
    can_read: bool = False
    can_write: bool = False
    exportable: bool = False
    bot_id: str | None = Field(
        default=None,
        description="Bot client that has access to this chat",
    )
