from __future__ import annotations

from app.metrics import ServiceMetrics


class TestServiceMetrics:
    def test_event_received_increments(self) -> None:
        m = ServiceMetrics()
        m.event_received("aibot")
        assert m.bot_events["aibot"].received == 1
        m.event_received("aibot")
        assert m.bot_events["aibot"].received == 2

    def test_event_matched_increments(self) -> None:
        m = ServiceMetrics()
        m.event_matched("aibot")
        assert m.bot_events["aibot"].matched == 1

    def test_event_published_increments(self) -> None:
        m = ServiceMetrics()
        m.event_published("supportbot")
        assert m.bot_events["supportbot"].published == 1

    def test_all_event_counters_independent(self) -> None:
        m = ServiceMetrics()
        m.event_received("aibot")
        m.event_matched("aibot")
        m.event_published("aibot")
        b = m.bot_events["aibot"]
        assert b.received == 1
        assert b.matched == 1
        assert b.published == 1

    def test_multiple_bots_are_independent(self) -> None:
        m = ServiceMetrics()
        m.event_received("aibot")
        m.event_received("supportbot")
        m.event_received("aibot")
        assert m.bot_events["aibot"].received == 2
        assert m.bot_events["supportbot"].received == 1

    def test_response_consumed(self) -> None:
        m = ServiceMetrics()
        m.response_consumed()
        assert m.responses.consumed == 1

    def test_response_sent(self) -> None:
        m = ServiceMetrics()
        m.response_sent()
        assert m.responses.sent == 1

    def test_response_failed(self) -> None:
        m = ServiceMetrics()
        m.response_failed()
        assert m.responses.failed == 1

    def test_all_response_counters(self) -> None:
        m = ServiceMetrics()
        m.response_consumed()
        m.response_sent()
        m.response_failed()
        assert m.responses.consumed == 1
        assert m.responses.sent == 1
        assert m.responses.failed == 1

    def test_snapshot_returns_expected_keys(self) -> None:
        m = ServiceMetrics()
        m.event_received("aibot")
        m.response_consumed()
        snap = m.snapshot()
        assert "uptime_seconds" in snap
        assert "bot_events" in snap
        assert "responses" in snap
        assert snap["bot_events"]["aibot"]["received"] == 1
        assert snap["responses"]["consumed"] == 1

    def test_started_at_is_set(self) -> None:
        m = ServiceMetrics()
        assert m.started_at is not None
