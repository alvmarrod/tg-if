from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.chat_exporter import (
    ChatExportEngine,
    _extract_media_info,
    _media_extension,
    _media_subdir,
    _monthly_filename,
    _serialize_message,
)
from domain.entities import ExportProgress, ExportState
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
    if has_forward:
        fwd = MagicMock()
        fwd.date = datetime(2026, 6, 14, tzinfo=timezone.utc)
        fwd.sender_user = MagicMock()
        fwd.sender_user.id = 999
        fwd.sender_user.first_name = "Forwarder"
        fwd.sender_user.last_name = None
        fwd.sender_user.username = "forwarder"
        msg.forward_origin = fwd
    else:
        msg.forward_origin = None
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

    def test_checkpoint_path(self, tmp_path: Path) -> None:
        config = AppConfig(export_storage_path=str(tmp_path))
        engine = ChatExportEngine(config=config, clients={})
        path = engine._checkpoint_path(-100123)
        assert str(path) == str(tmp_path / "-100123" / "_export_state.json")

    def test_checkpoint_none_when_missing(self, tmp_path: Path) -> None:
        config = AppConfig(export_storage_path=str(tmp_path))
        engine = ChatExportEngine(config=config, clients={})
        assert engine._load_checkpoint(-100123) is None

    def test_checkpoint_save_load_round_trip(self, tmp_path: Path) -> None:
        config = AppConfig(export_storage_path=str(tmp_path))
        engine = ChatExportEngine(config=config, clients={})
        engine._progress = ExportProgress(
            state=ExportState.PAUSED,
            current_chat_id=-100123,
            processed=42,
            media_count=5,
            media_bytes=1000,
            start_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        engine._progress_msg_id = 99
        engine._progress_chat_id = 888
        engine._export_offset_id = 500
        engine._export_since_msg_id = 10
        engine._export_since_date = None
        engine._export_bot_name = "testbot"
        engine._seen_file_ids = {"a", "b", "c"}

        engine._save_checkpoint()

        # Load into fresh engine
        fresh = ChatExportEngine(config=config, clients={})
        cp = fresh._load_checkpoint(-100123)
        assert cp is not None
        assert cp.chat_id == -100123
        assert cp.offset_id == 500
        assert cp.processed == 42
        assert cp.media_count == 5
        assert cp.media_bytes == 1000
        assert cp.progress_msg_id == 99
        assert cp.progress_chat_id == 888
        assert cp.since_msg_id == 10
        assert cp.since_date is None
        assert cp.bot_name == "testbot"
        assert sorted(cp.seen_file_ids) == ["a", "b", "c"]
        assert cp.saved_at is not None

    def test_checkpoint_delete_removes_file(self, tmp_path: Path) -> None:
        config = AppConfig(export_storage_path=str(tmp_path))
        engine = ChatExportEngine(config=config, clients={})
        engine._progress = ExportProgress(
            state=ExportState.PAUSED,
            current_chat_id=-100123,
        )
        engine._save_checkpoint()
        assert engine._checkpoint_path(-100123).exists()

        engine._delete_checkpoint(-100123)
        assert not engine._checkpoint_path(-100123).exists()

    def test_pause_does_not_save_checkpoint_directly(self, tmp_path: Path) -> None:
        """Checkpoint is saved at page boundary in _export_messages, not in pause()."""
        config = AppConfig(export_storage_path=str(tmp_path))
        engine = ChatExportEngine(config=config, clients={})
        engine._progress.state = ExportState.RUNNING
        engine._progress.current_chat_id = -100123
        engine.pause()

        assert not engine._checkpoint_path(-100123).exists()
        assert engine.state == ExportState.PAUSED

    def test_checkpoint_saved_at_page_boundary(self, tmp_path: Path) -> None:
        """Simulate page boundary: state PAUSED + offset updated → checkpoint saved."""
        config = AppConfig(export_storage_path=str(tmp_path))
        engine = ChatExportEngine(config=config, clients={})
        engine._progress = ExportProgress(
            state=ExportState.PAUSED,
            current_chat_id=-100123,
        )
        engine._export_offset_id = 500
        engine._progress.processed = 42
        engine._save_checkpoint()

        assert engine._checkpoint_path(-100123).exists()
        cp = engine._load_checkpoint(-100123)
        assert cp is not None
        assert cp.offset_id == 500
        assert cp.processed == 42

    def test_stale_checkpoint_reaped_on_new_export(self, tmp_path: Path) -> None:
        """A checkpoint for chat A is deleted when starting export for chat B."""
        config = AppConfig(export_storage_path=str(tmp_path))
        engine = ChatExportEngine(config=config, clients={})
        engine._progress = ExportProgress(
            state=ExportState.PAUSED,
            current_chat_id=-100111,
        )
        engine._export_offset_id = 10
        engine._save_checkpoint()
        stale_path = engine._checkpoint_path(-100111)
        assert stale_path.exists()

        # Simulate export_chat reaping logic for target -100123
        cp = engine._load_checkpoint(-100123)
        assert cp is None  # no checkpoint for target
        cp = engine._load_checkpoint(-100111)
        assert cp is not None and cp.chat_id != -100123
        # This is what export_chat does when cp.chat_id != chat_id
        engine._delete_checkpoint(cp.chat_id)
        assert not stale_path.exists()

    async def test_export_with_offset_passed_to_export_messages(
        self, engine: ChatExportEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """offset param flows to _export_messages as start_offset_id."""
        user_client = MagicMock()
        user_client.bot_id = "__user__"
        engine._user_client = user_client

        async def _get_chat_history(
            chat_id: int,
            limit: int = 0,
            offset_id: int = 0,
            offset_date: Any = None,
        ) -> list[MagicMock]:
            return [MagicMock()]

        user_client.get_chat_history = _get_chat_history

        hook: dict[str, Any] = {}

        async def _export_messages_hook(
            client: Any,
            chat_id: int,
            bot_name: str,
            since_msg_id: int | None,
            since_date: Any,
            parallelism: int,
            start_offset_id: int = 0,
        ) -> None:
            hook["start_offset_id"] = start_offset_id

        monkeypatch.setattr(engine, "_export_messages", _export_messages_hook)
        monkeypatch.setattr(engine, "_write_summary", AsyncMock())

        await engine.export_chat(chat_id=-100123, notify_chat_id=999, offset=500)
        assert hook.get("start_offset_id") == 500
