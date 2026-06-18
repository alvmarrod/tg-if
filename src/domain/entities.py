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


class ChatType(str, Enum):
    """Type of Telegram chat."""

    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class RoutingContext(BaseModel):
    """Metadata extracted from events for routing decisions."""

    chat_type: ChatType
    has_media: bool = False
    media_type: Optional[str] = None  # photo, video, document, audio, etc.
    user_role: Optional[str] = None  # creator, administrator, member
    command: Optional[str] = None  # e.g., "/start", "/help"
    is_reply: bool = False
    is_forward: bool = False

    model_config = ConfigDict(use_enum_values=True)


class TelegramEvent(BaseModel):
    """Base Telegram event (abstract)."""

    event_id: str = Field(..., description="Unique event identifier")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    bot_id: str = Field(..., description="Bot identifier")
    event_type: EventType
    chat_id: int
    user_id: int
    raw_payload: dict[str, Any] = Field(
        default_factory=dict, description="Raw Telegram update"
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
        description="send method: text, photo, document, video, audio, media_group, edit_message_text, answer_callback_query",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict, description="kwargs forwarded to the send method"
    )


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
