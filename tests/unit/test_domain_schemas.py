from __future__ import annotations

from datetime import datetime, timezone

from domain.schemas import AdminSignalType, FileInfo


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
