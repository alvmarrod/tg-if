from __future__ import annotations

from domain.entities import (
    ChatInfo,
    ChatType,
    ExportProgress,
    ExportState,
    MediaConfigRule,
    MediaScope,
    OutgoingResponse,
)


class TestMediaConfigRule:
    def test_minimal_construction(self) -> None:
        rule = MediaConfigRule(scope=MediaScope.GLOBAL, action="eager")
        assert rule.scope == MediaScope.GLOBAL
        assert rule.action == "eager"
        assert rule.scope_id is None
        assert rule.content_types == ["all"]

    def test_with_scope_id(self) -> None:
        rule = MediaConfigRule(scope=MediaScope.CHAT, scope_id="-100123", action="lazy")
        assert rule.scope == MediaScope.CHAT
        assert rule.scope_id == "-100123"
        assert rule.action == "lazy"

    def test_with_content_types(self) -> None:
        rule = MediaConfigRule(
            scope=MediaScope.USER,
            scope_id="42",
            action="eager",
            content_types=["photo", "video"],
        )
        assert rule.content_types == ["photo", "video"]


class TestOutgoingResponse:
    def test_required_fields(self) -> None:
        resp = OutgoingResponse(
            response_id="r1",
            correlation_id="e1",
            bot_id="aibot",
            chat_id=123,
            response_type="text",
        )
        assert resp.response_id == "r1"
        assert resp.correlation_id == "e1"
        assert resp.bot_id == "aibot"
        assert resp.chat_id == 123
        assert resp.response_type == "text"
        assert resp.payload == {}

    def test_with_payload(self) -> None:
        resp = OutgoingResponse(
            response_id="r2",
            correlation_id="e2",
            bot_id="aibot",
            chat_id=456,
            response_type="photo",
            payload={"photo": "file_id", "caption": "hi"},
        )
        assert resp.payload == {"photo": "file_id", "caption": "hi"}


class TestExportState:
    def test_enum_values(self) -> None:
        assert ExportState.IDLE.value == "idle"
        assert ExportState.RUNNING.value == "running"
        assert ExportState.PAUSED.value == "paused"
        assert ExportState.CANCELLED.value == "cancelled"

    def test_string_enum(self) -> None:
        assert str(ExportState.RUNNING) == "ExportState.RUNNING"


class TestExportProgress:
    def test_defaults(self) -> None:
        p = ExportProgress()
        assert p.total == 0
        assert p.processed == 0
        assert p.state == ExportState.IDLE
        assert p.media_count == 0
        assert p.media_bytes == 0
        assert p.current_chat_id is None
        assert p.pct == 0.0

    def test_pct_calculation(self) -> None:
        p = ExportProgress(total=100, processed=25)
        assert p.pct == 25.0

    def test_pct_rounding(self) -> None:
        p = ExportProgress(total=3, processed=1)
        assert p.pct == 33.3

    def test_pct_zero_total(self) -> None:
        p = ExportProgress(total=0, processed=50)
        assert p.pct == 0.0

    def test_pct_full(self) -> None:
        p = ExportProgress(total=200, processed=200)
        assert p.pct == 100.0

    def test_state_transition(self) -> None:
        p = ExportProgress(state=ExportState.RUNNING)
        assert p.state == ExportState.RUNNING
        p.state = ExportState.PAUSED
        assert p.state == ExportState.PAUSED


class TestChatInfo:
    def test_required_fields(self) -> None:
        info = ChatInfo(chat_id=-100123, title="Test Chat", chat_type=ChatType.GROUP)
        assert info.chat_id == -100123
        assert info.title == "Test Chat"
        assert info.chat_type == ChatType.GROUP
        assert info.members == 0
        assert info.exportable is False

    def test_minimal_prerequisites(self) -> None:
        info = ChatInfo(
            chat_id=-100456,
            title="Public Group",
            chat_type=ChatType.SUPERGROUP,
            can_read=True,
            exportable=True,
        )
        assert info.can_read is True
        assert info.exportable is True

    def test_private_chat(self) -> None:
        info = ChatInfo(
            chat_id=12345,
            title="User Name",
            chat_type=ChatType.PRIVATE,
            can_read=True,
            can_write=True,
        )
        assert info.chat_type == ChatType.PRIVATE
        assert info.bot_id is None
