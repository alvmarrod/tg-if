from __future__ import annotations

from domain.entities import MediaConfigRule, MediaScope, OutgoingResponse


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
