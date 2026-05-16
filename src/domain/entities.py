"""Domain entities for tg-if service."""

from enum import Enum
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field


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

    class Config:
        use_enum_values = True


class TelegramEvent(BaseModel):
    """Base Telegram event (abstract)."""

    event_id: str = Field(..., description="Unique event identifier")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    bot_id: str = Field(..., description="Bot identifier")
    event_type: EventType
    chat_id: int
    user_id: int
    raw_payload: dict[str, Any] = Field(
        default_factory=dict, description="Raw Telegram update"
    )

    class Config:
        use_enum_values = True


class MessageEvent(TelegramEvent):
    """Message-specific event (text, media messages)."""

    event_type: EventType = EventType.MESSAGE
    message_id: int
    text: Optional[str] = None
    caption: Optional[str] = None
    media_type: Optional[str] = None
    has_media: bool = False


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


class OutgoingMessage(BaseModel):
    """Abstract message to send to Telegram."""

    message_id: str = Field(..., description="Unique message identifier")
    bot_id: str = Field(..., description="Bot to send from")
    chat_id: int
    text: str
    reply_to_message_id: Optional[int] = None
    buttons: Optional[list[list[dict[str, str]]]] = Field(
        None, description="Button layout: list of rows, each row is list of buttons"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "message_id": "msg_123",
                "bot_id": "aibot",
                "chat_id": 12345,
                "text": "Hello! Choose an option:",
                "buttons": [
                    [{"text": "Option 1", "callback_data": "opt1"}],
                    [{"text": "Option 2", "callback_data": "opt2"}],
                ],
            }
        }
