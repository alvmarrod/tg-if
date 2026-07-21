from __future__ import annotations

from infrastructure.telegram.handlers import _detect_command, parse_session_path


class TestDetectCommand:
    def test_none_text(self) -> None:
        assert _detect_command(None) == (None, [])

    def test_empty_text(self) -> None:
        assert _detect_command("") == (None, [])

    def test_no_slash(self) -> None:
        assert _detect_command("hello world") == (None, [])

    def test_simple_command(self) -> None:
        assert _detect_command("/start") == ("start", [])

    def test_command_with_args(self) -> None:
        assert _detect_command("/start foo bar") == ("start", ["foo", "bar"])

    def test_command_with_bot_mention(self) -> None:
        assert _detect_command("/start@MyBot") == ("start", [])

    def test_command_with_bot_mention_and_args(self) -> None:
        assert _detect_command("/start@MyBot foo bar") == ("start", ["foo", "bar"])

    def test_just_slash(self) -> None:
        cmd, args = _detect_command("/")
        assert cmd == ""
        assert args == []

    def test_command_with_hyphen_normalized_to_underscore(self) -> None:
        assert _detect_command("/gb-start") == ("gb_start", [])

    def test_command_with_hyphen_and_args(self) -> None:
        assert _detect_command("/gb-start foo bar") == ("gb_start", ["foo", "bar"])


class TestParseSessionPath:
    def test_simple_path(self) -> None:
        assert parse_session_path("sessions/bot.session") == ("bot", "sessions")

    def test_nested_path(self) -> None:
        assert parse_session_path("/var/data/nested/bot.session") == (
            "bot",
            "/var/data/nested",
        )

    def test_no_directory(self) -> None:
        stem, parent = parse_session_path("single")
        assert stem == "single"
        assert parent == "."

    def test_empty_string(self) -> None:
        stem, parent = parse_session_path("")
        assert stem == ""
        assert parent == "."
