from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


from infrastructure.telegram.handlers import (
    _detect_command,
    _extract_from_user,
    _extract_media_info,
    _extract_reaction_emoji,
    _extract_reply_to_message,
    build_reply_markup,
    callback_to_event,
    context_from_callback,
    context_from_reaction_updated,
    edited_message_to_event,
    extract_routing_context,
    lock_session_file,
    message_to_event,
    parse_session_path,
    reaction_count_updated_to_event,
    reaction_updated_to_event,
)


def _user(**kw: Any) -> MagicMock:
    defaults: dict[str, Any] = dict(
        id=100,
        is_bot=False,
        first_name="Test",
        last_name=None,
        username=None,
        language_code=None,
    )
    defaults.update(kw)
    return MagicMock(**defaults)


def _chat(chat_id: int = -100123, chat_type: str = "supergroup") -> MagicMock:
    c = MagicMock()
    c.id = chat_id
    c.type = MagicMock(value=chat_type)
    c.title = "Test Chat"
    return c


def _basic_message(**kw: Any) -> MagicMock:
    defaults: dict[str, Any] = dict(
        id=1,
        chat=_chat(),
        from_user=_user(),
        text="hello world",
        caption=None,
        media=None,
        reply_to_message_id=None,
        reply_to_message=None,
        forward_origin=None,
        date=1700000000,
        photo=None,
        video=None,
        audio=None,
        document=None,
        animation=None,
        voice=None,
        video_note=None,
        sticker=None,
        message_id=1,
    )
    defaults.update(kw)
    return MagicMock(**defaults)


class TestDetectCommand:
    def test_none_text(self) -> None:
        assert _detect_command(None) == (None, [])

    def test_empty_text(self) -> None:
        assert _detect_command("") == (None, [])

    def test_no_slash(self) -> None:
        assert _detect_command("hello") == (None, [])

    def test_simple_command(self) -> None:
        assert _detect_command("/start") == ("start", [])

    def test_command_with_args(self) -> None:
        assert _detect_command("/help topic rules") == (
            "help",
            ["topic", "rules"],
        )

    def test_command_with_bot_suffix(self) -> None:
        assert _detect_command("/start@mybot") == ("start", [])

    def test_command_with_bot_suffix_and_args(self) -> None:
        assert _detect_command("/help@bot arg1 arg2") == (
            "help",
            ["arg1", "arg2"],
        )

    def test_command_with_dash(self) -> None:
        assert _detect_command("/upload-list") == ("upload_list", [])

    def test_command_with_leading_whitespace(self) -> None:
        assert _detect_command("  /start") == (None, [])


class TestExtractFromUser:
    def test_none_user(self) -> None:
        assert _extract_from_user(None) is None

    def test_basic_user(self) -> None:
        u = _user()
        result = _extract_from_user(u)
        assert result is not None
        assert result["id"] == 100
        assert result["is_bot"] is False
        assert result["first_name"] == "Test"
        assert result["last_name"] is None
        assert result["username"] is None

    def test_bot_user(self) -> None:
        u = _user(id=200, is_bot=True, first_name="Bot", username="botname")
        result = _extract_from_user(u)
        assert result is not None
        assert result["id"] == 200
        assert result["is_bot"] is True
        assert result["username"] == "botname"

    def test_user_with_last_name(self) -> None:
        u = _user(last_name="Doe")
        result = _extract_from_user(u)
        assert result["last_name"] == "Doe"


class TestExtractReplyToMessage:
    def test_none_reply(self) -> None:
        assert _extract_reply_to_message(None) is None

    def test_basic_reply(self) -> None:
        reply = MagicMock()
        reply.id = 42
        reply.from_user = _user(id=999, first_name="Replier")
        reply.text = "original"
        reply.caption = None
        result = _extract_reply_to_message(reply)
        assert result is not None
        assert result["message_id"] == 42
        assert result["text"] == "original"
        assert result["from_"] is not None
        assert result["from_"]["id"] == 999


class TestExtractReactionEmoji:
    def test_empty_list(self) -> None:
        assert _extract_reaction_emoji([]) is None

    def test_with_emoji(self) -> None:
        r = MagicMock(emoji="👍")
        assert _extract_reaction_emoji([r]) == "👍"

    def test_no_emoji_attr(self) -> None:
        r = MagicMock(spec=[])
        assert _extract_reaction_emoji([r]) is None

    def test_multiple_returns_first(self) -> None:
        r1 = MagicMock(emoji="🔥")
        r2 = MagicMock(emoji="❤️")
        assert _extract_reaction_emoji([r1, r2]) == "🔥"


class TestExtractMediaInfo:
    def test_no_media(self) -> None:
        msg = _basic_message()
        fid, fuid, raw = _extract_media_info(msg)
        assert fid is None
        assert fuid is None
        assert raw == {}

    def test_photo_media(self) -> None:
        photo = MagicMock(file_id="AgAC123", file_unique_id="QQAD123")
        msg = _basic_message(photo=photo)
        fid, fuid, raw = _extract_media_info(msg)
        assert fid == "AgAC123"
        assert fuid == "QQAD123"
        assert raw["file_id"] == "AgAC123"

    def test_video_media_with_extra_fields(self) -> None:
        video = MagicMock(
            file_id="BQAD456",
            file_unique_id="AAAD456",
            file_size=1024000,
            width=1920,
            height=1080,
            duration=120,
            mime_type="video/mp4",
        )
        msg = _basic_message(video=video)
        fid, fuid, raw = _extract_media_info(msg)
        assert fid == "BQAD456"
        assert raw["file_size"] == 1024000
        assert raw["duration"] == 120
        assert raw["mime_type"] == "video/mp4"

    def test_document_media(self) -> None:
        doc = MagicMock(
            file_id="doc_123",
            file_unique_id="doc_unique_123",
            file_name="report.pdf",
            mime_type="application/pdf",
        )
        msg = _basic_message(document=doc)
        fid, fuid, raw = _extract_media_info(msg)
        assert fid == "doc_123"
        assert raw["file_name"] == "report.pdf"

    def test_first_media_found_wins(self) -> None:
        photo = MagicMock(file_id="p1", file_unique_id="pu1")
        video = MagicMock(file_id="v1", file_unique_id="vu1")
        msg = _basic_message(photo=photo, video=video)
        fid, fuid, raw = _extract_media_info(msg)
        assert fid == "p1"


class TestMessageToEvent:
    def test_basic_text_message(self) -> None:
        msg = _basic_message()
        event = message_to_event("testbot", msg)
        assert event.event_type == "message"
        assert event.bot_id == "testbot"
        assert event.chat_id == -100123
        assert event.message_id == 1
        assert event.text == "hello world"
        assert event.has_media is False
        assert event.is_reply is False
        assert event.is_forward is False

    def test_command_detection(self) -> None:
        msg = _basic_message(text="/start")
        event = message_to_event("bot", msg)
        assert event.event_type == "command"
        assert event.command == "start"
        assert event.command_args == []

    def test_command_with_args(self) -> None:
        msg = _basic_message(text="/ban user123 reason")
        event = message_to_event("bot", msg)
        assert event.command == "ban"
        assert event.command_args == ["user123", "reason"]

    def test_message_with_media(self) -> None:
        media = MagicMock(value="photo")
        photo = MagicMock(file_id="f1", file_unique_id="fu1")
        msg = _basic_message(media=media, photo=photo)
        event = message_to_event("bot", msg)
        assert event.has_media is True
        assert event.media_type == "photo"
        assert event.file_id == "f1"
        assert event.file_unique_id == "fu1"

    def test_message_with_reply(self) -> None:
        reply = MagicMock()
        reply.id = 5
        reply.from_user = _user(id=200, first_name="Replier")
        reply.text = "replying"
        reply.caption = None
        msg = _basic_message(reply_to_message_id=5, reply_to_message=reply)
        event = message_to_event("bot", msg)
        assert event.is_reply is True
        assert event.reply_to_message_id == 5
        assert event.reply_to_message is not None
        assert event.reply_to_message["message_id"] == 5

    def test_message_with_forward(self) -> None:
        origin = MagicMock()
        msg = _basic_message(forward_origin=origin)
        event = message_to_event("bot", msg)
        assert event.is_forward is True

    def test_no_from_user(self) -> None:
        msg = _basic_message(from_user=None)
        event = message_to_event("bot", msg)
        assert event.user_id == 0
        assert event.from_user is None

    def test_command_no_from_user(self) -> None:
        msg = _basic_message(text="/cmd", from_user=None)
        event = message_to_event("bot", msg)
        assert event.user_id == 0


class TestEditedMessageToEvent:
    def test_basic_edited_text(self) -> None:
        msg = _basic_message(text="edited content")
        event = edited_message_to_event("bot", msg)
        assert event.event_type == "edited_message"
        assert event.text == "edited content"

    def test_edited_command(self) -> None:
        msg = _basic_message(text="/editcmd")
        event = edited_message_to_event("bot", msg)
        assert event.event_type == "edited_message"
        assert event.command == "editcmd"

    def test_edited_with_media(self) -> None:
        media = MagicMock(value="video")
        video = MagicMock(file_id="v99", file_unique_id="vu99")
        msg = _basic_message(text="look", media=media, video=video)
        event = edited_message_to_event("bot", msg)
        assert event.has_media is True
        assert event.media_type == "video"


class TestCallbackToEvent:
    def test_str_callback_data(self) -> None:
        query = MagicMock()
        query.id = "cb_1"
        query.data = "menu_main"
        query.from_user = _user(id=300)
        query.message = MagicMock()
        query.message.id = 10
        query.message.chat = _chat(chat_id=456, chat_type="private")
        event = callback_to_event("bot", query)
        assert event.event_type == "callback_query"
        assert event.callback_id == "cb_1"
        assert event.callback_data == "menu_main"
        assert event.message_id == 10
        assert event.chat_id == 456

    def test_bytes_callback_data(self) -> None:
        query = MagicMock()
        query.id = "cb_2"
        query.data = b"data\x00\x01"
        query.from_user = _user(id=301)
        query.message = MagicMock()
        query.message.id = 20
        query.message.chat = _chat(chat_id=789, chat_type="group")
        event = callback_to_event("bot", query)
        assert event.callback_data == "data\x00\x01"
        assert event.chat_id == 789

    def test_unexpected_data_type(self) -> None:
        query = MagicMock()
        query.id = "cb_3"
        query.data = 12345
        query.from_user = _user(id=302)
        query.message = MagicMock()
        query.message.id = 30
        query.message.chat = _chat()
        with pytest.raises(TypeError, match="Unexpected callback_data type"):
            callback_to_event("bot", query)

    def test_no_message(self) -> None:
        query = MagicMock()
        query.id = "cb_4"
        query.data = "data_no_msg"
        query.from_user = _user(id=303)
        query.message = None
        event = callback_to_event("bot", query)
        assert event.chat_id == 0
        assert event.message_id is None


class TestContextFromCallback:
    def test_with_message(self) -> None:
        query = MagicMock()
        query.message = MagicMock()
        query.message.chat = _chat(chat_type="channel")
        ctx = context_from_callback(query)
        assert ctx.chat_type == "channel"

    def test_without_message(self) -> None:
        query = MagicMock()
        query.message = None
        ctx = context_from_callback(query)
        assert ctx.chat_type == "private"


class TestExtractRoutingContext:
    def test_basic_message(self) -> None:
        msg = _basic_message()
        ctx = extract_routing_context(msg)
        assert ctx.chat_type == "supergroup"
        assert ctx.has_media is False
        assert ctx.media_type is None

    def test_message_with_media(self) -> None:
        media = MagicMock(value="photo")
        msg = _basic_message(media=media)
        ctx = extract_routing_context(msg)
        assert ctx.has_media is True
        assert ctx.media_type == "photo"

    def test_message_with_command(self) -> None:
        msg = _basic_message(text="/settings")
        ctx = extract_routing_context(msg)
        assert ctx.command == "settings"

    def test_message_without_chat_type(self) -> None:
        msg = _basic_message()
        msg.chat = MagicMock()
        msg.chat.id = 999
        msg.chat.type = None
        ctx = extract_routing_context(msg)
        assert ctx.chat_type == "private"

    def test_reply_and_forward(self) -> None:
        origin = MagicMock()
        reply = MagicMock()
        reply.id = 5
        reply.from_user = _user(id=200, first_name="R")
        reply.text = "orig"
        reply.caption = None
        msg = _basic_message(
            reply_to_message_id=5,
            reply_to_message=reply,
            forward_origin=origin,
        )
        ctx = extract_routing_context(msg)
        assert ctx.is_reply is True
        assert ctx.is_forward is True


class TestReactionUpdated:
    def test_reaction_updated_to_event(self) -> None:
        new_r = MagicMock(emoji="👍")
        old_r = MagicMock(emoji="👎")
        reaction = MagicMock()
        reaction.message_id = 42
        reaction.date = 1700000000
        reaction.chat = _chat(chat_id=-100, chat_type="channel")
        reaction.from_user = _user(id=500, first_name="Reactor")
        reaction.new_reaction = [new_r]
        reaction.old_reaction = [old_r]
        event = reaction_updated_to_event("bot", reaction)
        assert event.event_type == "message_reaction_updated"
        assert event.message_id == 42
        assert event.reaction_emoji == "👍"
        assert event.old_reaction_emoji == "👎"
        assert event.chat_id == -100

    def test_reaction_updated_no_old_reaction(self) -> None:
        new_r = MagicMock(emoji="❤️")
        reaction = MagicMock()
        reaction.message_id = 1
        reaction.date = 1700000000
        reaction.chat = _chat()
        reaction.from_user = _user(id=501)
        reaction.new_reaction = [new_r]
        reaction.old_reaction = []
        event = reaction_updated_to_event("bot", reaction)
        assert event.reaction_emoji == "❤️"
        assert event.old_reaction_emoji is None

    def test_reaction_updated_no_chat(self) -> None:
        reaction = MagicMock()
        reaction.message_id = 1
        reaction.date = 1700000000
        reaction.chat = None
        reaction.from_user = _user(id=502)
        reaction.new_reaction = []
        reaction.old_reaction = []
        event = reaction_updated_to_event("bot", reaction)
        assert event.chat_id == 0

    def test_context_from_reaction_updated(self) -> None:
        new_r = MagicMock(emoji="🎉")
        reaction = MagicMock()
        reaction.chat = _chat(chat_type="group")
        reaction.new_reaction = [new_r]
        reaction.old_reaction = []
        ctx = context_from_reaction_updated(reaction)
        assert ctx.chat_type == "group"
        assert ctx.reaction_emoji == "🎉"
        assert ctx.old_reaction_emoji is None

    def test_context_from_reaction_no_chat(self) -> None:
        reaction = MagicMock()
        reaction.chat = None
        reaction.new_reaction = []
        reaction.old_reaction = []
        ctx = context_from_reaction_updated(reaction)
        assert ctx.chat_type == "private"


class TestReactionCountUpdated:
    def test_reaction_count_updated_to_event(self) -> None:
        r1 = MagicMock(emoji="👍", count=5)
        r2 = MagicMock(emoji="❤️", count=3)
        reaction = MagicMock()
        reaction.message_id = 99
        reaction.date = 1700000000
        reaction.chat = _chat(chat_id=-999, chat_type="supergroup")
        reaction.from_user = None
        reaction.reactions = [r1, r2]
        event = reaction_count_updated_to_event("bot", reaction)
        assert event.event_type == "message_reaction_count_updated"
        assert event.message_id == 99
        assert event.chat_id == -999
        assert event.reactions == [
            {"emoji": "👍", "count": 5},
            {"emoji": "❤️", "count": 3},
        ]

    def test_reaction_count_updated_no_chat(self) -> None:
        reaction = MagicMock()
        reaction.message_id = 5
        reaction.date = 1700000000
        reaction.chat = None
        reaction.from_user = None
        reaction.reactions = []
        event = reaction_count_updated_to_event("bot", reaction)
        assert event.chat_id == 0
        assert event.reactions == []

    def test_reaction_count_updated_with_from_user(self) -> None:
        reaction = MagicMock()
        reaction.message_id = 7
        reaction.date = 1700000000
        reaction.chat = _chat()
        reaction.from_user = _user(id=600)
        reaction.reactions = []
        event = reaction_count_updated_to_event("bot", reaction)
        assert event.user_id == 600


class TestBuildReplyMarkup:
    def test_none_buttons(self) -> None:
        assert build_reply_markup(None) is None

    def test_empty_buttons(self) -> None:
        with pytest.raises(ValueError, match="requires non-empty buttons"):
            build_reply_markup([])

    def test_callback_button(self) -> None:
        markup = build_reply_markup([[{"text": "Click", "callback_data": "btn_click"}]])
        assert markup is not None
        assert markup.inline_keyboard[0][0].text == "Click"
        assert markup.inline_keyboard[0][0].callback_data == "btn_click"

    def test_url_button(self) -> None:
        markup = build_reply_markup([[{"text": "Visit", "url": "https://example.com"}]])
        assert markup is not None
        assert markup.inline_keyboard[0][0].url == "https://example.com"

    def test_web_app_button(self) -> None:
        markup = build_reply_markup(
            [
                [
                    {
                        "text": "Open App",
                        "web_app": {"url": "https://app.example.com"},
                    }
                ]
            ]
        )
        assert markup is not None
        btn = markup.inline_keyboard[0][0]
        assert btn.text == "Open App"
        assert btn.web_app is not None
        assert btn.web_app.url == "https://app.example.com"

    def test_web_app_missing_url(self) -> None:
        with pytest.raises(ValueError, match="web_app button requires non-empty 'url'"):
            build_reply_markup([[{"text": "Bad", "web_app": {"url": ""}}]])

    def test_web_app_missing_field(self) -> None:
        with pytest.raises(ValueError, match="web_app button requires 'web_app' field"):
            build_reply_markup([[{"text": "Bad", "web_app": None}]])

    def test_missing_button_type(self) -> None:
        with pytest.raises(
            ValueError,
            match="Button must have 'web_app', 'callback_data', or 'url'",
        ):
            build_reply_markup([[{"text": "Nothing"}]])  # pyright: ignore[reportArgumentType]

    def test_multiple_rows(self) -> None:
        markup = build_reply_markup(
            [
                [{"text": "A", "callback_data": "a"}],
                [{"text": "B", "callback_data": "b"}],
            ]
        )
        assert markup is not None
        assert len(markup.inline_keyboard) == 2

    def test_multiple_buttons_in_row(self) -> None:
        markup = build_reply_markup(
            [
                [
                    {"text": "A", "callback_data": "a"},
                    {"text": "B", "url": "https://b.com"},
                ]
            ]
        )
        assert markup is not None
        assert len(markup.inline_keyboard[0]) == 2


class TestParseSessionPath:
    def test_basic_path(self) -> None:
        name, parent = parse_session_path("sessions/mybot.session")
        assert name == "mybot"
        assert parent == "sessions"

    def test_subdirectory(self) -> None:
        name, parent = parse_session_path("data/sessions/user.session")
        assert name == "user"
        assert parent == "data/sessions"

    def test_no_extension(self) -> None:
        name, parent = parse_session_path("sessions/bot_no_ext")
        assert name == "bot_no_ext"
        assert parent == "sessions"


class TestSessionLock:
    def test_acquires_and_releases_lock(self, tmp_path: Any) -> None:
        session_path = str(tmp_path / "test.session")
        unlock = lock_session_file(session_path)
        assert callable(unlock)
        lock_file = tmp_path / "test.session.lock"
        assert lock_file.exists()
        unlock()
        unlock()

    def test_concurrent_lock_fails(self, tmp_path: Any) -> None:
        session_path = str(tmp_path / "shared.session")
        lock_session_file(session_path)
        with pytest.raises(RuntimeError, match="Could not acquire session lock"):
            lock_session_file(session_path, timeout=0.1)
