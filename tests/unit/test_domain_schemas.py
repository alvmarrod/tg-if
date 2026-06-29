from __future__ import annotations

from datetime import datetime, timezone

from domain.schemas import AdminSignalType, FileInfo, UploadEntry


class TestFileInfo:
    def test_construct_with_all_fields(self) -> None:
        dt = datetime.now(timezone.utc)
        fi = FileInfo(
            bot_id="aibot",
            file_unique_id="abc123",
            ext="jpg",
            size=1024,
            accesses=3,
            last_access=dt,
            stored_at=dt,
        )
        assert fi.bot_id == "aibot"
        assert fi.file_unique_id == "abc123"
        assert fi.ext == "jpg"
        assert fi.size == 1024
        assert fi.accesses == 3
        assert fi.last_access is dt
        assert fi.stored_at is dt

    def test_last_access_can_be_none(self) -> None:
        dt = datetime.now(timezone.utc)
        fi = FileInfo(
            bot_id="b",
            file_unique_id="x",
            ext="png",
            size=512,
            accesses=0,
            last_access=None,
            stored_at=dt,
        )
        assert fi.last_access is None


class TestAdminSignalType:
    def test_values(self) -> None:
        assert AdminSignalType.RESPONSE_FAILED.value == "response_failed"
        assert AdminSignalType.COMPONENT_CONNECTED.value == "component_connected"
        assert AdminSignalType.COMPONENT_DISCONNECTED.value == "component_disconnected"
        assert AdminSignalType.CONFIG_WARNING.value == "config_warning"

    def test_is_str_enum(self) -> None:
        assert issubclass(AdminSignalType, str)
        assert isinstance(AdminSignalType.RESPONSE_FAILED, str)


class TestUploadEntry:
    def test_construct_with_all_fields(self) -> None:
        entry = UploadEntry(
            content_hash="a1b2c3d4",
            url_hash="url_hash_1",
            url="https://example.com/video.mp4",
            file_id="AgAC...",
            file_unique_id="QQAD...",
            bot_id="supportbot",
            ext="mp4",
            size=45_000_000,
            created_at=1000.0,
            last_used_at=2000.0,
            use_count=3,
        )
        assert entry.content_hash == "a1b2c3d4"
        assert entry.url_hash == "url_hash_1"
        assert entry.url == "https://example.com/video.mp4"
        assert entry.file_id == "AgAC..."
        assert entry.file_unique_id == "QQAD..."
        assert entry.bot_id == "supportbot"
        assert entry.ext == "mp4"
        assert entry.size == 45_000_000
        assert entry.created_at == 1000.0
        assert entry.last_used_at == 2000.0
        assert entry.use_count == 3

    def test_defaults(self) -> None:
        entry = UploadEntry(
            content_hash="abc",
            bot_id="b",
            size=123,
        )
        assert entry.url_hash is None
        assert entry.url is None
        assert entry.file_id is None
        assert entry.file_unique_id is None
        assert entry.ext == "bin"
        assert entry.created_at == 0.0
        assert entry.last_used_at == 0.0
        assert entry.use_count == 0

    def test_minimal_construct(self) -> None:
        entry = UploadEntry(content_hash="x", bot_id="y", size=1)
        assert entry.content_hash == "x"
        assert entry.bot_id == "y"
        assert entry.size == 1
