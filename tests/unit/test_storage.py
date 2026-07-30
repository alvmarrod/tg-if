from __future__ import annotations

from pathlib import Path

from infrastructure.media.storage import DiskStorage


class TestDiskStorageLRU:
    def test_no_eviction_when_under_limit(self, tmp_path: Path) -> None:
        s = DiskStorage(str(tmp_path), max_tracked_files=5)
        for i in range(3):
            s._touch_access(f"bot/file_{i}")
        assert len(s._accesses) == 3
        assert len(s._last_access) == 3

    def test_evicts_lru_when_over_limit(self, tmp_path: Path) -> None:
        import time

        s = DiskStorage(str(tmp_path), max_tracked_files=2)
        s._touch_access("bot/a")
        time.sleep(0.001)
        s._touch_access("bot/b")
        time.sleep(0.001)
        s._touch_access("bot/a")  # a re-touched, b is old
        time.sleep(0.001)
        s._touch_access("bot/c")  # should evict b
        assert len(s._accesses) == 2
        assert "bot/a" in s._accesses
        assert "bot/c" in s._accesses
        assert "bot/b" not in s._accesses

    def test_zero_limit_disables_eviction(self, tmp_path: Path) -> None:
        s = DiskStorage(str(tmp_path), max_tracked_files=0)
        for i in range(100):
            s._touch_access(f"bot/file_{i}")
        assert len(s._accesses) == 100

    def test_store_and_retrieve_update_access(self, tmp_path: Path) -> None:
        s = DiskStorage(str(tmp_path), max_tracked_files=10)
        import asyncio

        async def run() -> None:
            await s.store("bot", "file1", b"data", "bin")
            await s.store("bot", "file2", b"more", "bin")
            await s.retrieve("bot", "file1")
            assert s._accesses["bot/file1"] == 2
            assert s._accesses["bot/file2"] == 1

        asyncio.run(run())

    def test_default_constructor(self, tmp_path: Path) -> None:
        s = DiskStorage(str(tmp_path))
        assert s._max_tracked == 0
