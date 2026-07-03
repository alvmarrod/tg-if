from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.chat_exporter import ChatExportEngine
from domain.entities import ExportCheckpoint, ExportState
from infrastructure.config import AppConfig

CHAT_ID = -100123
BOT_NAME = "testbot"


def _make_msg(
    msg_id: int,
    text: str | None = "Hello",
    date: datetime | None = None,
    file_unique_id: str | None = None,
    media_type: str = "photo",
    has_reactions: bool = False,
) -> MagicMock:
    msg = MagicMock()
    msg.id = msg_id
    msg.text = text
    msg.caption = None
    msg.date = date or datetime(2026, 6, 15, tzinfo=timezone.utc)
    msg.edit_date = None
    msg.reply_to_message_id = None
    msg.forward_origin = None
    msg.from_user = MagicMock()
    msg.from_user.id = 123
    msg.from_user.is_bot = False
    msg.from_user.first_name = "Alice"
    msg.from_user.last_name = None
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

    if file_unique_id is not None:
        media_mock = MagicMock()
        media_mock.file_unique_id = file_unique_id
        media_mock.file_id = f"file_{file_unique_id}"
        media_mock.file_size = 5000
        media_mock.mime_type = "image/jpeg"
        media_mock.file_name = None
        media_mock.width = 800
        media_mock.height = 600
        media_mock.duration = None
        if media_type == "photo":
            msg.photo = media_mock
        elif media_type == "video":
            msg.video = media_mock

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


def _page_sequence(
    *page_sets: list[list[MagicMock]], probe: list[MagicMock] | None = None
) -> MagicMock:
    """Create a mock TelegramClient that serves pre-defined pages.

    Each arg is a list of pages for one pass through get_chat_history.
    The engine calls _resolve_client() first as a probe — use ``probe=``
    to supply a dedicated page for that call so the real page-sets
    aren't shifted by one.
    """
    client = MagicMock()
    client.bot_id = BOT_NAME
    calls: list[list[MagicMock]] = []
    if probe is not None:
        calls.append(probe)
    for pages in page_sets:
        calls.extend(pages)
    call_idx: int = 0

    async def get_chat_history(
        chat_id: int,
        limit: int = 0,
        offset_id: int = 0,
        offset_date: Any = None,
    ) -> list[MagicMock]:
        nonlocal call_idx
        if call_idx >= len(calls):
            return []
        result = calls[call_idx]
        call_idx += 1
        return result

    async def _download_media(message: MagicMock, file_path: str, **kwargs: Any) -> str:
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("mock")
        return file_path

    client.get_chat_history = get_chat_history
    client.download_media = AsyncMock(side_effect=_download_media)
    return client


@pytest.fixture
def export_dir(tmp_path: Path) -> Path:
    return tmp_path / "exports"


@pytest.fixture
def config(export_dir: Path) -> AppConfig:
    return AppConfig(export_storage_path=str(export_dir))


@pytest.fixture
def admin_client() -> MagicMock:
    client = MagicMock()
    client.send_text = AsyncMock(return_value=MagicMock(id=99))
    client.edit_message_text = AsyncMock()
    client.bot_id = "__admin__"
    return client


def _make_engine(
    config: AppConfig,
    mock_client: MagicMock,
    admin_client: MagicMock,
    user_client: MagicMock | None = None,
) -> ChatExportEngine:
    engine = ChatExportEngine(
        config=config,
        clients={BOT_NAME: mock_client},
        admin_client=admin_client,
    )
    if user_client is not None:
        engine._user_client = user_client
    return engine


async def _delayed_cancel(engine: ChatExportEngine, delay: float = 0.02) -> None:
    import asyncio

    await asyncio.sleep(delay)
    engine.cancel()


class TestExportFlow:
    async def test_basic_export_creates_monthly_jsonl(
        self, export_dir: Path, config: AppConfig, admin_client: MagicMock
    ) -> None:
        msgs = [
            _make_msg(1, "msg one"),
            _make_msg(2, "msg two"),
            _make_msg(3, "msg three"),
        ]
        client = _page_sequence([msgs, []], [msgs, []], probe=msgs)
        engine = _make_engine(config, client, admin_client, user_client=client)
        await engine.export_chat(chat_id=CHAT_ID, notify_chat_id=999)

        monthly = export_dir / str(CHAT_ID) / "2026-06.json"
        assert monthly.exists()
        lines = monthly.read_text().strip().split("\n")
        assert len(lines) == 3
        for i, line in enumerate(lines):
            obj = json.loads(line)
            assert obj["message_id"] == i + 1

        summary_path = export_dir / str(CHAT_ID) / "_summary.json"
        assert summary_path.exists()
        summary = json.loads(summary_path.read_text())
        assert summary["message_count"] == 3
        assert summary["chat_id"] == CHAT_ID
        assert "2026-06.json" in summary["files"]

    async def test_export_spans_multiple_months(
        self, export_dir: Path, config: AppConfig, admin_client: MagicMock
    ) -> None:
        msgs = [
            _make_msg(1, "jun", datetime(2026, 6, 15, tzinfo=timezone.utc)),
            _make_msg(2, "jul", datetime(2026, 7, 1, tzinfo=timezone.utc)),
            _make_msg(3, "aug", datetime(2026, 8, 10, tzinfo=timezone.utc)),
        ]
        client = _page_sequence([msgs, []], [msgs, []], probe=msgs)
        engine = _make_engine(config, client, admin_client, user_client=client)
        await engine.export_chat(chat_id=CHAT_ID, notify_chat_id=999)

        for fname in ("2026-06.json", "2026-07.json", "2026-08.json"):
            fpath = export_dir / str(CHAT_ID) / fname
            assert fpath.exists(), f"Missing {fname}"

        summary_path = export_dir / str(CHAT_ID) / "_summary.json"
        summary = json.loads(summary_path.read_text())
        assert sorted(summary["files"]) == [
            "2026-06.json",
            "2026-07.json",
            "2026-08.json",
        ]

    async def test_export_with_media_dedup(
        self, export_dir: Path, config: AppConfig, admin_client: MagicMock
    ) -> None:
        msgs = [
            _make_msg(1, "photo a", file_unique_id="abc123"),
            _make_msg(2, "photo a again", file_unique_id="abc123"),
            _make_msg(3, "photo b", file_unique_id="def456"),
        ]
        client = _page_sequence([msgs, []], [msgs, []], probe=msgs)
        engine = _make_engine(config, client, admin_client, user_client=client)
        await engine.export_chat(chat_id=CHAT_ID, notify_chat_id=999)

        assert client.download_media.await_count == 2

        monthly = export_dir / str(CHAT_ID) / "2026-06.json"
        lines = monthly.read_text().strip().split("\n")
        obj1 = json.loads(lines[0])
        obj2 = json.loads(lines[1])
        obj3 = json.loads(lines[2])

        assert obj1["media"]["file_unique_id"] == "abc123"
        assert obj2["media"]["file_unique_id"] == "abc123"
        assert obj3["media"]["file_unique_id"] == "def456"
        assert obj1["media"]["local_path"] == obj2["media"]["local_path"]

    async def test_export_with_reactions(
        self, export_dir: Path, config: AppConfig, admin_client: MagicMock
    ) -> None:
        msgs = [
            _make_msg(1, "with reactions", has_reactions=True),
            _make_msg(2, "no reactions"),
        ]
        client = _page_sequence([msgs, []], [msgs, []], probe=msgs)
        engine = _make_engine(config, client, admin_client, user_client=client)
        await engine.export_chat(chat_id=CHAT_ID, notify_chat_id=999)

        monthly = export_dir / str(CHAT_ID) / "2026-06.json"
        lines = monthly.read_text().strip().split("\n")
        obj1 = json.loads(lines[0])
        assert "reactions" in obj1
        assert len(obj1["reactions"]) == 2
        obj2 = json.loads(lines[1])
        assert "reactions" not in obj2

    async def test_export_pagination(
        self, export_dir: Path, config: AppConfig, admin_client: MagicMock
    ) -> None:
        page1 = [_make_msg(i) for i in range(1, 101)]
        page2 = [_make_msg(i) for i in range(101, 151)]
        client = _page_sequence(
            [page1, page2, []],
            [page1, page2, []],
            probe=page1,
        )
        engine = _make_engine(config, client, admin_client, user_client=client)
        await engine.export_chat(chat_id=CHAT_ID, notify_chat_id=999)

        monthly = export_dir / str(CHAT_ID) / "2026-06.json"
        lines = monthly.read_text().strip().split("\n")
        assert len(lines) == 150

        summary_path = export_dir / str(CHAT_ID) / "_summary.json"
        summary = json.loads(summary_path.read_text())
        assert summary["message_count"] == 150

    async def test_export_with_since_message_id(
        self, export_dir: Path, config: AppConfig, admin_client: MagicMock
    ) -> None:
        msgs = [
            _make_msg(10, "old"),
            _make_msg(20, "mid"),
            _make_msg(30, "recent"),
        ]
        client = _page_sequence([msgs, []], [msgs, []], probe=msgs)
        engine = _make_engine(config, client, admin_client, user_client=client)
        await engine.export_chat(chat_id=CHAT_ID, notify_chat_id=999, since=20)

        monthly = export_dir / str(CHAT_ID) / "2026-06.json"
        lines = monthly.read_text().strip().split("\n")
        assert len(lines) == 2
        ids = [json.loads(line)["message_id"] for line in lines]
        assert ids == [20, 30]

    async def test_export_with_since_date(
        self, export_dir: Path, config: AppConfig, admin_client: MagicMock
    ) -> None:
        msgs = [
            _make_msg(1, "old", datetime(2026, 5, 1, tzinfo=timezone.utc)),
            _make_msg(2, "mid", datetime(2026, 6, 15, tzinfo=timezone.utc)),
            _make_msg(3, "recent", datetime(2026, 7, 1, tzinfo=timezone.utc)),
        ]
        client = _page_sequence([msgs, []], [msgs, []], probe=msgs)
        engine = _make_engine(config, client, admin_client, user_client=client)
        await engine.export_chat(
            chat_id=CHAT_ID, notify_chat_id=999, since="2026-06-01"
        )

        monthly = export_dir / str(CHAT_ID) / "2026-06.json"
        if monthly.exists():
            lines = monthly.read_text().strip().split("\n")
            ids = [json.loads(line)["message_id"] for line in lines]
            assert 1 not in ids

    async def test_export_cancel_clean_exit(
        self, export_dir: Path, config: AppConfig, admin_client: MagicMock
    ) -> None:
        msgs = [_make_msg(i) for i in range(1, 101)]
        client = _page_sequence([msgs, []], [msgs, []], probe=msgs)
        engine = _make_engine(config, client, admin_client, user_client=client)

        import asyncio

        cancel_task = asyncio.create_task(_delayed_cancel(engine))
        await engine.export_chat(chat_id=CHAT_ID, notify_chat_id=999)
        await cancel_task

        monthly = export_dir / str(CHAT_ID) / "2026-06.json"
        assert monthly.exists()
        lines = monthly.read_text().strip().split("\n")
        assert len(lines) > 0

    async def test_export_summary_content(
        self, export_dir: Path, config: AppConfig, admin_client: MagicMock
    ) -> None:
        dt = datetime(2026, 6, 15, 12, 30, tzinfo=timezone.utc)
        msgs = [
            _make_msg(1, "first", dt),
            _make_msg(2, "with media", dt, file_unique_id="abc"),
            _make_msg(3, "last", dt),
        ]
        client = _page_sequence([msgs, []], [msgs, []], probe=msgs)
        engine = _make_engine(config, client, admin_client, user_client=client)
        await engine.export_chat(chat_id=CHAT_ID, notify_chat_id=999)

        summary_path = export_dir / str(CHAT_ID) / "_summary.json"
        summary = json.loads(summary_path.read_text())
        assert summary["message_count"] == 3
        assert summary["media_count"] == 1
        assert summary["media_total_bytes"] > 0
        assert summary["chat_id"] == CHAT_ID
        assert isinstance(summary["exported_at"], str)
        assert isinstance(summary["files"], list)
        assert "2026-06.json" in summary["files"]

    async def test_user_client_export(
        self, export_dir: Path, config: AppConfig, admin_client: MagicMock
    ) -> None:
        msgs = [_make_msg(1, "via user"), _make_msg(2, "via user too")]
        user_client = _page_sequence([msgs, []], [msgs, []], probe=msgs)
        engine = _make_engine(
            config, user_client, admin_client, user_client=user_client
        )
        await engine.export_chat(chat_id=CHAT_ID, notify_chat_id=999)

        monthly = export_dir / str(CHAT_ID) / "2026-06.json"
        assert monthly.exists()
        lines = monthly.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["message_id"] == 1

    async def test_resume_from_checkpoint_across_restarts(
        self, export_dir: Path, config: AppConfig, admin_client: MagicMock
    ) -> None:
        """Pause → process restart → /export → resume completes without duplicates."""
        page1 = [_make_msg(i) for i in range(1, 51)]
        page2 = [_make_msg(i) for i in range(51, 101)]

        cp = ExportCheckpoint(
            chat_id=CHAT_ID,
            offset_id=50,
            seen_file_ids=[],
            processed=50,
            bot_name=BOT_NAME,
        )
        cp_path = export_dir / str(CHAT_ID) / "_export_state.json"
        cp_path.parent.mkdir(parents=True, exist_ok=True)
        cp_path.write_text(cp.model_dump_json(indent=2), encoding="utf-8")

        client = _page_sequence([page2, []], [page2, []], probe=page1)
        engine = _make_engine(config, client, admin_client, user_client=client)

        async def _delayed_resume() -> None:
            import asyncio

            await asyncio.sleep(0.05)
            assert engine.state == ExportState.PAUSED, (
                f"Expected PAUSED, got {engine.state}"
            )
            engine.resume()

        import asyncio

        resume_task = asyncio.create_task(_delayed_resume())
        await engine.export_chat(chat_id=CHAT_ID, notify_chat_id=999)
        await resume_task

        monthly = export_dir / str(CHAT_ID) / "2026-06.json"
        lines = monthly.read_text().strip().split("\n")
        assert len(lines) == 50
        ids = [json.loads(line)["message_id"] for line in lines]
        assert ids == list(range(51, 101))

        assert not cp_path.exists(), "Checkpoint should be deleted on completion"

    async def test_export_with_offset_skips_newer_messages(
        self, export_dir: Path, config: AppConfig, admin_client: MagicMock
    ) -> None:
        """--offset <msg_id> skips paginated fetch for messages >= that ID."""
        older = [_make_msg(i) for i in range(1, 51)]  # IDs 1-50
        client = MagicMock()
        client.bot_id = BOT_NAME
        offset_ids: list[int] = []

        async def _get_chat_history(
            chat_id: int,
            limit: int = 0,
            offset_id: int = 0,
            offset_date: Any = None,
        ) -> list[MagicMock]:
            offset_ids.append(offset_id)
            if offset_id >= 50:
                return []
            return older

        async def _download_media(
            message: MagicMock, file_path: str, **kwargs: Any
        ) -> str:
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("mock")
            return file_path

        client.get_chat_history = _get_chat_history
        client.download_media = AsyncMock(side_effect=_download_media)
        engine = _make_engine(config, client, admin_client, user_client=client)

        await engine.export_chat(chat_id=CHAT_ID, notify_chat_id=999, offset=50)

        # First call is the probe (limit=1), second is the export fetch
        assert 50 in offset_ids, f"offset_id=50 should be used, got {offset_ids}"

        monthly = export_dir / str(CHAT_ID) / "2026-06.json"
        assert not monthly.exists(), "No messages should be exported"
