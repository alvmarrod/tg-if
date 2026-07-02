from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.chat_exporter import (
    ChatExportEngine,
    _extract_media_info,
    _format_progress_bar,
    _media_extension,
    _media_subdir,
    _monthly_filename,
    _serialize_message,
)
from domain.entities import ExportState
from infrastructure.config import AppConfig


def _make_config() -> AppConfig:
    return AppConfig(
        export_storage_path="/tmp/test_exports",
    )


def _make_msg(
    msg_id: int = 1,
    text: str | None = "Hello",
    date: datetime | None = None,
    has_media: bool = False,
    media_type: str = "photo",
    file_unique_id: str | None = None,
    has_reactions: bool = False,
    reply_to: int | None = None,
    has_forward: bool = False,
) -> MagicMock:
    msg = MagicMock()
    msg.id = msg_id
    msg.text = text
    msg.caption = None
    msg.date = date or datetime(2026, 6, 15, tzinfo=timezone.utc)
    msg.edit_date = None
    msg.reply_to_message_id = reply_to
    msg.forward_date = (
        datetime(2026, 6, 14, tzinfo=timezone.utc) if has_forward else None
    )
    msg.forward_from = MagicMock() if has_forward else None
    if msg.forward_from:
        msg.forward_from.id = 999
        msg.forward_from.first_name = "Forwarder"
        msg.forward_from.last_name = None
        msg.forward_from.username = "forwarder"
    msg.from_user = MagicMock()
    msg.from_user.id = 123
    msg.from_user.is_bot = False
    msg.from_user.first_name = "Alice"
    msg.from_user.last_name = "Smith"
    msg.from_user.username = "alice"
    msg.from_user.language_code = "en"
    msg.photo = None
    msg.video = None
    msg.audio = None
    msg.document = None
    msg.animation = None
    msg.sticker = None
    msg.video_note = None
    msg.voice = None
    msg.reactions = None

    if has_media:
        media_mock = MagicMock()
        media_mock.file_unique_id = file_unique_id or f"fid_{msg_id}"
        media_mock.file_id = f"file_{msg_id}"
        media_mock.file_size = 12345
        media_mock.mime_type = "image/jpeg"
        media_mock.file_name = "photo.jpg"
        media_mock.width = 800
        media_mock.height = 600
        media_mock.duration = None
        if media_type == "photo":
            msg.photo = media_mock
        elif media_type == "video":
            msg.video = media_mock
        elif media_type == "audio":
            msg.audio = media_mock
        elif media_type == "document":
            msg.document = media_mock
        elif media_type == "sticker":
            msg.sticker = media_mock
        elif media_type == "animation":
            msg.animation = media_mock

    if has_reactions:
        msg.reactions = MagicMock()
        r1 = MagicMock()
        r1.emoji = "+1"
        r1.count = 3
        r2 = MagicMock()
        r2.emoji = "heart"
        r2.count = 1
        msg.reactions.reactions = [r1, r2]

    return msg


class TestHelpers:
    def test_format_progress_bar_empty(self) -> None:
        bar = _format_progress_bar(0, 0)
        assert bar == "⬜" * 20

    def test_format_progress_bar_full(self) -> None:
        bar = _format_progress_bar(100, 100)
        assert bar == "⬛" * 20

    def test_format_progress_bar_half(self) -> None:
        bar = _format_progress_bar(50, 100)
        assert bar == "⬛" * 10 + "⬜" * 10

    def test_monthly_filename(self) -> None:
        dt = datetime(2026, 7, 1, tzinfo=timezone.utc)
        assert _monthly_filename(dt) == "2026-07.json"

    def test_monthly_filename_january(self) -> None:
        dt = datetime(2026, 1, 15, tzinfo=timezone.utc)
        assert _monthly_filename(dt) == "2026-01.json"

    def test_media_subdir_photo(self) -> None:
        assert _media_subdir("photo") == "photo"

    def test_media_subdir_video(self) -> None:
        assert _media_subdir("video") == "video"

    def test_media_subdir_voice(self) -> None:
        assert _media_subdir("voice") == "audio"

    def test_media_subdir_unknown(self) -> None:
        assert _media_subdir("unknown") == "other"

    def test_media_ext_photo(self) -> None:
        msg = _make_msg(has_media=True, media_type="photo")
        assert _media_extension(msg) == ".jpg"

    def test_media_ext_no_media(self) -> None:
        msg = _make_msg(has_media=False)
        assert _media_extension(msg) == ".bin"

    def test_serialize_message_basic(self) -> None:
        dt = datetime(2026, 6, 15, 12, 30, tzinfo=timezone.utc)
        msg = _make_msg(msg_id=42, text="Hello", date=dt)
        out = _serialize_message(msg)
        assert out["message_id"] == 42
        assert out["text"] == "Hello"
        assert out["date"] == "2026-06-15T12:30:00+00:00"
        assert out["from_user"]["id"] == 123
        assert out["from_user"]["username"] == "alice"
        assert "media" not in out

    def test_serialize_message_with_media(self) -> None:
        msg = _make_msg(
            msg_id=10,
            text="A photo",
            has_media=True,
            media_type="photo",
            file_unique_id="fid_abc",
        )
        out = _serialize_message(msg, media_rel_path="media/photo/fid_abc.jpg")
        assert out["media"] is not None
        assert out["media"]["type"] == "photo"
        assert out["media"]["file_unique_id"] == "fid_abc"
        assert out["media"]["local_path"] == "media/photo/fid_abc.jpg"
        assert out["media"]["width"] == 800

    def test_serialize_message_with_reactions(self) -> None:
        msg = _make_msg(msg_id=5, text="With reactions", has_reactions=True)
        out = _serialize_message(msg)
        assert out["reactions"] is not None
        assert len(out["reactions"]) == 2

    def test_serialize_message_reply(self) -> None:
        msg = _make_msg(msg_id=7, text="Reply text", reply_to=3)
        out = _serialize_message(msg)
        assert out["reply_to_message_id"] == 3

    def test_serialize_message_forward(self) -> None:
        msg = _make_msg(msg_id=8, text="Forwarded", has_forward=True)
        out = _serialize_message(msg)
        assert out["is_forward"] is True
        assert out["forward_from"]["id"] == 999

    def test_extract_media_info_photo(self) -> None:
        msg = _make_msg(has_media=True, media_type="photo", file_unique_id="fid_x")
        info = _extract_media_info(msg)
        assert info is not None
        assert info["type"] == "photo"
        assert info["file_unique_id"] == "fid_x"

    def test_extract_media_info_no_media(self) -> None:
        msg = _make_msg(has_media=False)
        assert _extract_media_info(msg) is None


@pytest.fixture
def engine() -> ChatExportEngine:
    config = _make_config()
    clients: dict[str, MagicMock] = {}
    admin = MagicMock()
    admin.send_text = AsyncMock(return_value=MagicMock(id=99))
    admin.edit_message_text = AsyncMock()
    eng = ChatExportEngine(config=config, clients=clients, admin_client=admin)
    return eng


class TestChatExportEngine:
    def test_initial_state(self, engine: ChatExportEngine) -> None:
        assert engine.state == ExportState.IDLE
        assert engine.progress.processed == 0

    def test_pause(self, engine: ChatExportEngine) -> None:
        engine._progress.state = ExportState.RUNNING
        engine.pause()
        assert engine.state == ExportState.PAUSED

    def test_resume(self, engine: ChatExportEngine) -> None:
        engine._progress.state = ExportState.PAUSED
        engine.resume()
        assert engine.state == ExportState.RUNNING

    def test_pause_idle_noop(self, engine: ChatExportEngine) -> None:
        engine.pause()
        assert engine.state == ExportState.IDLE

    def test_resume_not_paused_noop(self, engine: ChatExportEngine) -> None:
        engine.resume()
        assert engine.state == ExportState.IDLE

    def test_cancel(self, engine: ChatExportEngine) -> None:
        engine._progress.state = ExportState.RUNNING
        engine.cancel()
        assert engine.state == ExportState.CANCELLED
        assert engine._cancelled.is_set()

    async def test_export_rejects_concurrent(self, engine: ChatExportEngine) -> None:
        engine._lock = MagicMock()
        engine._lock.locked.return_value = True
        with pytest.raises(RuntimeError, match="already in progress"):
            await engine.export_chat(chat_id=-100123, notify_chat_id=999)

    async def test_export_no_client(self, engine: ChatExportEngine) -> None:
        with pytest.raises(RuntimeError, match="Chat export requires a user account"):
            await engine.export_chat(chat_id=-100123, notify_chat_id=999)

    async def test_user_client_for_export_success(
        self, engine: ChatExportEngine
    ) -> None:
        user_client = MagicMock()
        user_client.bot_id = "__user__"

        async def _get_chat_history(
            chat_id: int,
            limit: int = 0,
            offset_id: int = 0,
            offset_date: Any = None,
        ) -> list[MagicMock]:
            return [MagicMock()]

        user_client.get_chat_history = _get_chat_history
        engine._user_client = user_client
        result = await engine._user_client_for_export(-100123)
        assert result is user_client

    async def test_user_client_for_export_missing(
        self, engine: ChatExportEngine
    ) -> None:
        with pytest.raises(RuntimeError, match="Chat export requires a user account"):
            await engine._user_client_for_export(-100123)

    async def test_resolve_client_via_known_chats(
        self, engine: ChatExportEngine
    ) -> None:
        bot_client = MagicMock()
        bot_client.known_chats = [
            {"chat_id": -100123, "title": "Target", "type": "supergroup"},
        ]
        engine._clients = {"bot_a": bot_client}

        result = await engine._resolve_client(-100123)
        assert result is bot_client

    def test_find_bot_name(self) -> None:
        config = _make_config()
        client_a = MagicMock()
        client_a.bot_id = "bot_a"
        clients = {"bot_a": client_a}
        engine = ChatExportEngine(config=config, clients=clients)
        assert engine._find_bot_name(client_a) == "bot_a"
        assert engine._find_bot_name(MagicMock()) == "unknown"
