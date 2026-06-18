from app.bot_command_registry import BotCommandRegistry


class TestBotCommandRegistry:
    def test_register_single_subscriber(self) -> None:
        registry = BotCommandRegistry()
        result = registry.register(
            "aibot",
            "svc_1",
            [{"command": "start", "description": "Start"}],
        )
        assert result.status == "ok"
        assert result.registered == ["start"]
        assert result.conflicts == []

    def test_register_multiple_commands(self) -> None:
        registry = BotCommandRegistry()
        result = registry.register(
            "aibot",
            "svc_1",
            [
                {"command": "start", "description": "Start"},
                {"command": "help", "description": "Help"},
            ],
        )
        assert result.status == "ok"
        assert result.registered == ["help", "start"]

    def test_merge_two_subscribers_different_commands(self) -> None:
        registry = BotCommandRegistry()
        registry.register(
            "aibot",
            "svc_1",
            [{"command": "start", "description": "Start"}],
        )
        result = registry.register(
            "aibot",
            "svc_2",
            [{"command": "help", "description": "Help"}],
        )
        assert result.status == "ok"
        assert result.registered == ["help"]
        merged = registry.get_commands("aibot")
        names = {c["command"] for c in merged}
        assert names == {"start", "help"}

    def test_merge_with_dedup_same_subscriber_reregisters(self) -> None:
        registry = BotCommandRegistry()
        registry.register(
            "aibot",
            "svc_1",
            [{"command": "start", "description": "Start"}],
        )
        result = registry.register(
            "aibot",
            "svc_1",
            [{"command": "start", "description": "Updated Start"}],
        )
        assert result.status == "ok"
        merged = registry.get_commands("aibot")
        assert len(merged) == 1
        assert merged[0]["description"] == "Updated Start"

    def test_conflict_detected(self) -> None:
        registry = BotCommandRegistry()
        registry.register(
            "aibot",
            "svc_1",
            [{"command": "start", "description": "Start"}],
        )
        result = registry.register(
            "aibot",
            "svc_2",
            [{"command": "start", "description": "Also Start"}],
        )
        assert result.status == "nok"
        assert len(result.conflicts) == 1
        assert "svc_1" in result.conflicts[0]
        assert result.registered == []

    def test_conflict_multiple_overlaps(self) -> None:
        registry = BotCommandRegistry()
        registry.register(
            "aibot",
            "svc_1",
            [
                {"command": "start", "description": "Start"},
                {"command": "stop", "description": "Stop"},
            ],
        )
        result = registry.register(
            "aibot",
            "svc_2",
            [
                {"command": "start", "description": "Also Start"},
                {"command": "help", "description": "Help"},
                {"command": "stop", "description": "Also Stop"},
            ],
        )
        assert result.status == "nok"
        assert len(result.conflicts) == 2

    def test_no_conflict_different_bots(self) -> None:
        registry = BotCommandRegistry()
        registry.register(
            "aibot",
            "svc_1",
            [{"command": "start", "description": "Start"}],
        )
        result = registry.register(
            "supportbot",
            "svc_2",
            [{"command": "start", "description": "Start"}],
        )
        assert result.status == "ok"

    def test_deregister_removes_commands(self) -> None:
        registry = BotCommandRegistry()
        registry.register(
            "aibot",
            "svc_1",
            [{"command": "start", "description": "Start"}],
        )
        registry.register(
            "aibot",
            "svc_2",
            [{"command": "help", "description": "Help"}],
        )
        result = registry.deregister("aibot", "svc_1")
        assert result.status == "ok"
        assert result.registered == ["start"]
        merged = registry.get_commands("aibot")
        names = {c["command"] for c in merged}
        assert names == {"help"}

    def test_deregister_unknown_subscriber(self) -> None:
        registry = BotCommandRegistry()
        result = registry.deregister("aibot", "nonexistent")
        assert result.status == "nok"

    def test_deregister_unknown_bot(self) -> None:
        registry = BotCommandRegistry()
        result = registry.deregister("unknown_bot", "svc_1")
        assert result.status == "nok"

    def test_get_commands_empty_when_no_registrations(self) -> None:
        registry = BotCommandRegistry()
        assert registry.get_commands("aibot") == []

    def test_register_with_empty_commands_list(self) -> None:
        registry = BotCommandRegistry()
        result = registry.register("aibot", "svc_1", [])
        assert result.status == "nok"

    def test_get_commands_dedup_same_command_name(self) -> None:
        registry = BotCommandRegistry()
        registry.register(
            "aibot",
            "svc_1",
            [{"command": "start", "description": "Start"}],
        )
        registry.register(
            "aibot",
            "svc_2",
            [{"command": "start", "description": "Also Start"}],
        )
        # second register should fail with conflict
        merged = registry.get_commands("aibot")
        # svc_1's registration persists; only start from svc_1
        assert len(merged) == 1
        assert merged[0]["description"] == "Start"
