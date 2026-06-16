from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from app.admin_commands import AdminCommandHandler
from domain.entities import ChatType, CommandEvent, RoutingContext
from domain.rules import RoutingRule


class MockClient:
    def __init__(self) -> None:
        self.bot_id = "__admin__"
        self.send_text = AsyncMock()
        self.health = AsyncMock(return_value=True)


class MockManager:
    def __init__(self) -> None:
        self.health = AsyncMock(return_value=True)


class MockRule:
    def __init__(self, condition: dict[str, str], target: str) -> None:
        self.condition = condition
        self.target = target


class MockDispatcher:
    def __init__(self) -> None:
        self.rules: dict[str, list[RoutingRule]] = {}

    def add_rule(self, bot_name: str, rule: RoutingRule) -> None:
        self.rules.setdefault(bot_name, []).append(rule)

    def remove_rule(self, bot_name: str, idx: int) -> RoutingRule | None:
        rules = self.rules.get(bot_name)
        if rules is None or idx < 0 or idx >= len(rules):
            return None
        return rules.pop(idx)

    def get_rules(self, bot_name: str | None = None) -> dict[str, list[RoutingRule]]:
        if bot_name is not None:
            return {bot_name: self.rules.get(bot_name, [])}
        return dict(self.rules)


def _make_handler(
    *,
    admin_client: Any = None,
    user_id: int = 999,
    clients: Any = None,
    manager: Any = None,
    config: Any = None,
    metrics: Any = None,
    log_buffer: Any = None,
    dispatcher: Any = None,
    on_shutdown: Any = None,
) -> AdminCommandHandler:
    ac: Any = MockClient() if admin_client is None else admin_client
    mg: Any = MockManager() if manager is None else manager
    cfg: Any = _make_config() if config is None else config
    met: Any = _make_metrics() if metrics is None else metrics
    cls: Any = {} if clients is None else clients
    disp: Any = MockDispatcher() if dispatcher is None else dispatcher
    return AdminCommandHandler(
        admin_client=ac,
        user_id=user_id,
        clients=cls,
        manager=mg,
        config=cfg,
        metrics=met,
        dispatcher=disp,
        log_buffer=log_buffer,
        on_shutdown=on_shutdown,
    )


def _make_config() -> object:
    bot_a_rules = [
        MockRule(
            {"event_type": "command", "command_starts_with": "/admin"},
            "incoming.events.aibot.commands.admin",
        ),
        MockRule(
            {"event_type": "message", "has_media": "false"},
            "incoming.events.aibot.messages.text",
        ),
        MockRule({}, "incoming.events.aibot.unhandled"),
    ]
    bot_b_rules = [
        MockRule({"event_type": "command"}, "incoming.events.supportbot.commands"),
    ]
    return type(
        "MockConfig",
        (),
        {
            "bots": [
                type("MockBot", (), {"name": "aibot", "routing_rules": bot_a_rules})(),
                type(
                    "MockBot", (), {"name": "supportbot", "routing_rules": bot_b_rules}
                )(),
            ]
        },
    )()


def _make_metrics() -> object:
    from app.metrics import ServiceMetrics

    m = ServiceMetrics()
    m.event_received("aibot")
    m.event_received("aibot")
    m.event_received("supportbot")
    m.event_matched("aibot")
    m.event_matched("supportbot")
    m.event_published("aibot")
    m.event_published("supportbot")
    m.response_consumed()
    m.response_consumed()
    m.response_sent()
    m.response_failed()
    return m


def _make_event(command: str, args: list[str] | None = None) -> CommandEvent:
    return CommandEvent(
        event_id="1",
        bot_id="__admin__",
        chat_id=999,
        user_id=999,
        message_id=1,
        command=command,
        command_args=args or [],
        text=f"/{command}",
    )


def _private_context() -> RoutingContext:
    return RoutingContext(chat_type=ChatType.PRIVATE)


class TestAdminCommands:
    async def test_help_shows_available_commands(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin)
        await handler.handle(_make_event("help"), _private_context())
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        text = args[0][1]
        assert "Available commands" in text
        assert "/ping" in text
        assert "/status" in text
        assert "/target" in text
        assert "/rule-add" in text
        assert "/rule-remove" in text
        assert "/shutdown" in text

    async def test_unknown_command(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin)
        await handler.handle(_make_event("foobar"), _private_context())
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        assert "Unknown command" in args[0][1]

    async def test_status_shows_connections_and_metrics(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin)
        await handler.handle(_make_event("status"), _private_context())
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        text = args[0][1]
        assert "Service Control Panel" in text
        assert "broker" in text
        assert "aibot" in text
        assert "supportbot" in text
        assert "admin" in text
        assert "recv:" in text
        assert "match:" in text
        assert "publish:" in text
        assert "consumed:" in text
        assert "sent:" in text
        assert "failed: 1" in text
        assert "Active Targets" in text
        assert "Config Rules" in text

    async def test_bots_lists_configured_bots(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin)
        await handler.handle(_make_event("bots"), _private_context())
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        text = args[0][1]
        assert "Configured bots" in text
        assert "aibot" in text
        assert "3 rules" in text
        assert "supportbot" in text
        assert "1 rules" in text

    async def test_rules_shows_all_bots(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin)
        await handler.handle(_make_event("rules"), _private_context())
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        text = args[0][1]
        assert "Routing rules for aibot" in text
        assert "Routing rules for supportbot" in text
        assert "event_type=command" in text
        assert "(catch-all)" in text

    async def test_rules_with_bot_filter(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin)
        await handler.handle(
            _make_event("rules", ["--bot", "aibot"]), _private_context()
        )
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        text = args[0][1]
        assert "Routing rules for aibot" in text
        assert "supportbot" not in text

    async def test_rules_with_unknown_bot(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin)
        await handler.handle(
            _make_event("rules", ["--bot", "nonexistent"]), _private_context()
        )
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        assert "No bots configured" in args[0][1]

    async def test_log_shows_recent_entries(self) -> None:
        admin = MockClient()
        log_buffer = type(
            "MockLog",
            (),
            {
                "recent": lambda self, n: [
                    {
                        "timestamp": "2026-06-14T12:30:01",
                        "level": "INFO",
                        "event": "starting",
                        "extra": {"version": "0.1.0"},
                    },
                    {
                        "timestamp": "2026-06-14T12:30:05",
                        "level": "INFO",
                        "event": "service started",
                        "extra": {},
                    },
                ]
            },
        )()
        handler = _make_handler(admin_client=admin, log_buffer=log_buffer)
        await handler.handle(_make_event("log"), _private_context())
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        text = args[0][1]
        assert "Recent logs" in text
        assert "starting" in text
        assert "version=0.1.0" in text

    async def test_log_no_buffer_returns_error(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin, log_buffer=None)
        await handler.handle(_make_event("log"), _private_context())
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        assert "Log buffer not available" in args[0][1]

    async def test_ignores_events_from_other_users(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin)
        event = _make_event("help")
        event.chat_id = 111  # different user
        await handler.handle(event, _private_context())
        admin.send_text.assert_not_called()

    async def test_ignores_non_command_events(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin)
        from domain.entities import MessageEvent

        event = MessageEvent(
            event_id="2",
            bot_id="__admin__",
            chat_id=999,
            user_id=999,
            message_id=2,
            text="hello",
        )
        await handler.handle(event, _private_context())
        admin.send_text.assert_not_called()

    async def test_ping_returns_pong(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin)
        await handler.handle(_make_event("ping"), _private_context())
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        assert args[0][1] == "pong"

    async def test_target_unknown_target(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin)
        await handler.handle(_make_event("target", ["nonexistent"]), _private_context())
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        assert "No data for target" in args[0][1]

    async def test_target_requires_arg(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin)
        await handler.handle(_make_event("target"), _private_context())
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        assert "Usage: /target" in args[0][1]

    async def test_rule_add_missing_args(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin)
        await handler.handle(_make_event("rule-add"), _private_context())
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        assert "Usage" in args[0][1]
        assert "/rule-add" in args[0][1]

    async def test_rule_add_appends_rule(self) -> None:
        admin = MockClient()
        dispatcher = MockDispatcher()
        handler = _make_handler(admin_client=admin, dispatcher=dispatcher)
        await handler.handle(
            _make_event("rule-add", ["--bot", "aibot", "--target", "test_topic"]),
            _private_context(),
        )
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        assert "Rule added to aibot" in args[0][1]
        assert "test_topic" in args[0][1]
        assert len(dispatcher.rules.get("aibot", [])) == 1
        assert dispatcher.rules["aibot"][0].target == "test_topic"

    async def test_rule_add_with_condition(self) -> None:
        admin = MockClient()
        dispatcher = MockDispatcher()
        handler = _make_handler(admin_client=admin, dispatcher=dispatcher)
        await handler.handle(
            _make_event(
                "rule-add",
                [
                    "--bot",
                    "aibot",
                    "--target",
                    "test_topic",
                    "--condition",
                    "event_type=message",
                ],
            ),
            _private_context(),
        )
        admin.send_text.assert_awaited_once()
        rule = dispatcher.rules["aibot"][0]
        assert rule.condition == {"event_type": "message"}
        assert rule.target == "test_topic"

    async def test_rule_remove_missing_args(self) -> None:
        admin = MockClient()
        handler = _make_handler(admin_client=admin)
        await handler.handle(_make_event("rule-remove"), _private_context())
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        assert "Usage" in args[0][1]

    async def test_rule_remove_removes_rule(self) -> None:
        admin = MockClient()
        dispatcher = MockDispatcher()
        dispatcher.add_rule("aibot", RoutingRule(condition={}, target="topic_a"))
        dispatcher.add_rule("aibot", RoutingRule(condition={}, target="topic_b"))
        handler = _make_handler(admin_client=admin, dispatcher=dispatcher)
        await handler.handle(
            _make_event("rule-remove", ["--bot", "aibot", "--index", "1"]),
            _private_context(),
        )
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        assert "Rule 1 removed from aibot" in args[0][1]
        assert len(dispatcher.rules["aibot"]) == 1
        assert dispatcher.rules["aibot"][0].target == "topic_b"

    async def test_rule_remove_invalid_index(self) -> None:
        admin = MockClient()
        dispatcher = MockDispatcher()
        dispatcher.add_rule("aibot", RoutingRule(condition={}, target="topic_a"))
        handler = _make_handler(admin_client=admin, dispatcher=dispatcher)
        await handler.handle(
            _make_event("rule-remove", ["--bot", "aibot", "--index", "5"]),
            _private_context(),
        )
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        assert "No rule at index" in args[0][1]

    async def test_rule_remove_nonexistent_bot(self) -> None:
        admin = MockClient()
        dispatcher = MockDispatcher()
        handler = _make_handler(admin_client=admin, dispatcher=dispatcher)
        await handler.handle(
            _make_event("rule-remove", ["--bot", "nonexistent", "--index", "1"]),
            _private_context(),
        )
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        assert "No rule at index" in args[0][1]

    async def test_shutdown_calls_callback(self) -> None:
        admin = MockClient()
        shutdown_called = False

        async def fake_shutdown() -> None:
            nonlocal shutdown_called
            shutdown_called = True

        handler = _make_handler(admin_client=admin, on_shutdown=fake_shutdown)
        await handler.handle(_make_event("shutdown"), _private_context())
        admin.send_text.assert_awaited_once()
        args = admin.send_text.await_args
        assert args is not None
        assert "Shutting down" in args[0][1]
        assert shutdown_called
