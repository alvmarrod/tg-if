from __future__ import annotations

import time
from collections.abc import Generator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from domain.schemas import UploadEntry
from infrastructure.sqlite import UploadRegistry


@pytest.fixture
def registry() -> Generator[UploadRegistry, Any, None]:
    tmp = TemporaryDirectory()
    db_path = str(Path(tmp.name) / "uploads.db")
    reg = UploadRegistry(db_path)
    reg.connect()
    yield reg
    reg.close()
    tmp.cleanup()


class TestUploadRegistry:
    def test_register_and_get_by_hash(self, registry: UploadRegistry) -> None:
        entry = UploadEntry(
            content_hash="abc123",
            bot_id="supportbot",
            ext="jpg",
            size=42_000,
        )
        registry.register(entry)

        retrieved = registry.get_by_hash("abc123")
        assert retrieved is not None
        assert retrieved.content_hash == "abc123"
        assert retrieved.bot_id == "supportbot"
        assert retrieved.ext == "jpg"
        assert retrieved.size == 42_000
        assert retrieved.url_hash is None
        assert retrieved.url is None
        assert retrieved.file_id is None
        assert retrieved.file_unique_id is None
        assert retrieved.created_at > 0
        assert retrieved.last_used_at > 0
        assert retrieved.use_count == 0

    def test_get_by_hash_not_found(self, registry: UploadRegistry) -> None:
        assert registry.get_by_hash("nonexistent") is None

    def test_register_with_url_hash(self, registry: UploadRegistry) -> None:
        entry = UploadEntry(
            content_hash="def456",
            url_hash="url_hash_1",
            url="https://example.com/file.jpg",
            bot_id="aibot",
            ext="jpg",
            size=1000,
        )
        registry.register(entry)

        retrieved = registry.get_by_url_hash("url_hash_1")
        assert retrieved is not None
        assert retrieved.content_hash == "def456"
        assert retrieved.url == "https://example.com/file.jpg"

    def test_get_by_url_hash_not_found(self, registry: UploadRegistry) -> None:
        assert registry.get_by_url_hash("no_such_hash") is None

    def test_register_idempotent_raises(self, registry: UploadRegistry) -> None:
        entry = UploadEntry(content_hash="dup", bot_id="b", size=1)
        registry.register(entry)
        with pytest.raises(Exception):  # sqlite3.IntegrityError
            registry.register(entry)

    def test_update_file_id(self, registry: UploadRegistry) -> None:
        entry = UploadEntry(content_hash="abc", bot_id="b", size=100)
        registry.register(entry)
        registry.update_file_id("abc", "AgAC...", "QQAD...")

        retrieved = registry.get_by_hash("abc")
        assert retrieved is not None
        assert retrieved.file_id == "AgAC..."
        assert retrieved.file_unique_id == "QQAD..."
        assert retrieved.use_count == 1

    def test_update_file_id_increments_use_count(
        self, registry: UploadRegistry
    ) -> None:
        entry = UploadEntry(content_hash="xyz", bot_id="b", size=100)
        registry.register(entry)
        registry.update_file_id("xyz", "fid", "fuid")
        registry.update_file_id("xyz", "fid2", "fuid2")

        retrieved = registry.get_by_hash("xyz")
        assert retrieved is not None
        assert retrieved.use_count == 2
        assert retrieved.file_id == "fid2"

    def test_touch_usage(self, registry: UploadRegistry) -> None:
        entry = UploadEntry(content_hash="abc", bot_id="b", size=100)
        registry.register(entry)
        time.sleep(0.01)

        before = registry.get_by_hash("abc")
        assert before is not None
        before_used = before.last_used_at

        registry.touch_usage("abc")

        after = registry.get_by_hash("abc")
        assert after is not None
        assert after.last_used_at > before_used
        assert after.use_count == 1

    def test_list_all(self, registry: UploadRegistry) -> None:
        registry.register(UploadEntry(content_hash="a1", bot_id="bot1", size=1))
        registry.register(UploadEntry(content_hash="a2", bot_id="bot1", size=2))
        registry.register(UploadEntry(content_hash="a3", bot_id="bot2", size=3))

        all_entries = registry.list_all()
        assert len(all_entries) == 3

    def test_list_all_filter_by_bot(self, registry: UploadRegistry) -> None:
        registry.register(UploadEntry(content_hash="a1", bot_id="bot1", size=1))
        registry.register(UploadEntry(content_hash="a2", bot_id="bot1", size=2))
        registry.register(UploadEntry(content_hash="a3", bot_id="bot2", size=3))

        bot1_entries = registry.list_all(bot_id="bot1")
        assert len(bot1_entries) == 2
        assert all(e.bot_id == "bot1" for e in bot1_entries)

    def test_delete(self, registry: UploadRegistry) -> None:
        registry.register(UploadEntry(content_hash="del_me", bot_id="b", size=1))
        assert registry.get_by_hash("del_me") is not None

        deleted = registry.delete("del_me")
        assert deleted is True
        assert registry.get_by_hash("del_me") is None

    def test_delete_not_found(self, registry: UploadRegistry) -> None:
        deleted = registry.delete("nonexistent")
        assert deleted is False

    def test_purge_all(self, registry: UploadRegistry) -> None:
        registry.register(UploadEntry(content_hash="x1", bot_id="b", size=1))
        registry.register(UploadEntry(content_hash="x2", bot_id="b", size=1))
        registry.register(UploadEntry(content_hash="x3", bot_id="b", size=1))

        count = registry.purge_all()
        assert count == 3
        assert registry.list_all() == []

    def test_round_trip_full_entry(self, registry: UploadRegistry) -> None:
        entry = UploadEntry(
            content_hash="full",
            url_hash="url_h",
            url="https://example.com/full.mp4",
            bot_id="supportbot",
            ext="mp4",
            size=45_000_000,
        )
        registry.register(entry)
        registry.update_file_id("full", "AgAC...", "QQAD...")

        retrieved = registry.get_by_hash("full")
        assert retrieved is not None
        assert retrieved.content_hash == "full"
        assert retrieved.url_hash == "url_h"
        assert retrieved.url == "https://example.com/full.mp4"
        assert retrieved.file_id == "AgAC..."
        assert retrieved.file_unique_id == "QQAD..."
        assert retrieved.bot_id == "supportbot"
        assert retrieved.ext == "mp4"
        assert retrieved.size == 45_000_000
        assert retrieved.created_at > 0
        assert retrieved.last_used_at > 0
        assert retrieved.use_count == 1

    def test_auto_connect(self) -> None:
        tmp = TemporaryDirectory()
        db_path = str(Path(tmp.name) / "auto.db")
        reg = UploadRegistry(db_path)
        try:
            reg.get_by_hash("x")
        finally:
            reg.close()
            tmp.cleanup()

    def test_close_idempotent(self, registry: UploadRegistry) -> None:
        registry.close()
        registry.close()
