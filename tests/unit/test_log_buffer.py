from __future__ import annotations

from app.log_buffer import LogBuffer


class TestLogBuffer:
    def test_processor_appends_event(self) -> None:
        buf = LogBuffer(max_size=10)
        event_dict = {"timestamp": "t1", "event": "hello", "logger": "test"}
        result = buf.processor(None, "info", event_dict)
        assert result is event_dict
        recent = buf.recent(1)
        assert len(recent) == 1
        assert recent[0]["event"] == "hello"
        assert recent[0]["level"] == "INFO"

    def test_processor_captures_extra_keys(self) -> None:
        buf = LogBuffer(max_size=10)
        buf.processor(
            None,
            "warning",
            {"event": "test", "timestamp": "t1", "logger": "x", "user_id": 42},
        )
        recent = buf.recent(1)
        assert recent[0]["extra"] == {"user_id": 42}

    def test_processor_swallows_exception(self) -> None:
        buf = LogBuffer(max_size=10)

        class Bad:
            def __getitem__(self, _: str) -> object:
                raise RuntimeError("boom")

        result = buf.processor(None, "info", Bad())  # type: ignore[arg-type]
        assert result is not None

    def test_recent_returns_all_when_n_larger_than_buffer(self) -> None:
        buf = LogBuffer(max_size=5)
        for i in range(3):
            buf.processor(None, "info", {"event": str(i), "logger": ""})
        recent = buf.recent(100)
        assert len(recent) == 3

    def test_recent_respects_max_size(self) -> None:
        buf = LogBuffer(max_size=3)
        for i in range(5):
            buf.processor(None, "info", {"event": str(i), "logger": ""})
        assert len(buf.recent(10)) == 3
        assert buf.recent(10)[-1]["event"] == "4"
