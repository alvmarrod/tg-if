from domain.entities import (
    CallbackQueryEvent,
    ChatType,
    CommandEvent,
    EventType,
    MessageEvent,
    RoutingContext,
    TelegramEvent,
)
from domain.rules import (
    RoutingDecision,
    RoutingRule,
    RulesEngine,
    _match_condition,
    resolve_subtype,
)


class TestResolveSubtype:
    def test_message_text(self, message_event_text: MessageEvent) -> None:
        assert resolve_subtype(message_event_text) == "text"

    def test_message_photo(self, message_event_photo: MessageEvent) -> None:
        assert resolve_subtype(message_event_photo) == "photo"

    def test_command(self, command_event: CommandEvent) -> None:
        assert resolve_subtype(command_event) == "text"

    def test_callback(self, callback_event: CallbackQueryEvent) -> None:
        assert resolve_subtype(callback_event) == "text"


class TestMatchCondition:
    def test_empty_condition_always_matches(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        assert _match_condition({}, message_event_text, private_context) is True

    def test_event_type_match(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        cond = {"event_type": "message"}
        assert _match_condition(cond, message_event_text, private_context) is True

    def test_event_type_no_match(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        cond = {"event_type": "callback_query"}
        assert _match_condition(cond, message_event_text, private_context) is False

    def test_event_subtype_match(
        self, message_event_photo: MessageEvent, private_context: RoutingContext
    ) -> None:
        cond = {"event_subtype": "photo"}
        assert _match_condition(cond, message_event_photo, private_context) is True

    def test_event_subtype_no_match(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        cond = {"event_subtype": "photo"}
        assert _match_condition(cond, message_event_text, private_context) is False

    def test_chat_type_match(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        cond = {"chat_type": "private"}
        assert _match_condition(cond, message_event_text, private_context) is True

    def test_chat_type_no_match(
        self, message_event_text: MessageEvent, group_context: RoutingContext
    ) -> None:
        cond = {"chat_type": "private"}
        assert _match_condition(cond, message_event_text, group_context) is False

    def test_command_match(self, command_event: CommandEvent) -> None:
        ctx = RoutingContext(chat_type=ChatType.PRIVATE, command="start")
        cond = {"command": "start"}
        assert _match_condition(cond, command_event, ctx) is True

    def test_command_no_match(self, command_event: CommandEvent) -> None:
        ctx = RoutingContext(chat_type=ChatType.PRIVATE, command="start")
        cond = {"command": "help"}
        assert _match_condition(cond, command_event, ctx) is False

    def test_command_starts_with_match(self, command_event: CommandEvent) -> None:
        ctx = RoutingContext(chat_type=ChatType.PRIVATE, command="start")
        cond = {"command_starts_with": "sta"}
        assert _match_condition(cond, command_event, ctx) is True

    def test_command_starts_with_no_match(self, command_event: CommandEvent) -> None:
        ctx = RoutingContext(chat_type=ChatType.PRIVATE, command="start")
        cond = {"command_starts_with": "xyz"}
        assert _match_condition(cond, command_event, ctx) is False

    def test_command_starts_with_no_command(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        cond = {"command_starts_with": "hello"}
        assert _match_condition(cond, message_event_text, private_context) is False

    def test_has_media_match(
        self,
        message_event_photo: MessageEvent,
        media_context: RoutingContext,
    ) -> None:
        cond = {"has_media": True}
        assert _match_condition(cond, message_event_photo, media_context) is True

    def test_has_media_no_match(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        cond = {"has_media": True}
        assert _match_condition(cond, message_event_text, private_context) is False

    def test_media_type_match(
        self,
        message_event_photo: MessageEvent,
        media_context: RoutingContext,
    ) -> None:
        cond = {"media_type": "photo"}
        assert _match_condition(cond, message_event_photo, media_context) is True

    def test_media_type_no_match(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        cond = {"media_type": "photo"}
        assert _match_condition(cond, message_event_text, private_context) is False

    def test_user_role_match(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        ctx = private_context.model_copy(update={"user_role": "administrator"})
        cond = {"user_role": "administrator"}
        assert _match_condition(cond, message_event_text, ctx) is True

    def test_user_role_no_match(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        cond = {"user_role": "administrator"}
        assert _match_condition(cond, message_event_text, private_context) is False

    def test_user_role_none_vs_string(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        cond = {"user_role": "administrator"}
        assert _match_condition(cond, message_event_text, private_context) is False

    def test_multiple_conditions_all_match(
        self,
        message_event_text: MessageEvent,
        private_context: RoutingContext,
    ) -> None:
        cond = {"event_type": "message", "chat_type": "private"}
        assert _match_condition(cond, message_event_text, private_context) is True

    def test_multiple_conditions_one_fails(
        self,
        message_event_text: MessageEvent,
        private_context: RoutingContext,
    ) -> None:
        cond = {"event_type": "message", "chat_type": "group"}
        assert _match_condition(cond, message_event_text, private_context) is False

    def test_unknown_key_is_ignored(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        cond = {"unknown_field": "whatever"}
        assert _match_condition(cond, message_event_text, private_context) is True


class TestResolveSubtypeEdgeCases:
    def test_unknown_event_type_returns_none(self) -> None:
        event: TelegramEvent = TelegramEvent(
            event_id="1",
            bot_id="test",
            event_type=EventType.INLINE_QUERY,
            chat_id=0,
            user_id=0,
        )
        assert resolve_subtype(event) is None


class TestRulesEngineEvaluate:
    def test_first_match_returned(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        rules = [
            RoutingRule(condition={"event_type": "callback_query"}, target="topic_b"),
            RoutingRule(condition={"event_type": "message"}, target="topic_a"),
        ]
        decision = RulesEngine.evaluate(message_event_text, private_context, rules)
        assert decision == RoutingDecision(matched=True, target="topic_a", rule_idx=1)

    def test_no_match(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        rules = [
            RoutingRule(condition={"event_type": "callback_query"}, target="topic_b"),
        ]
        decision = RulesEngine.evaluate(message_event_text, private_context, rules)
        assert decision == RoutingDecision(matched=False)

    def test_empty_rules_list(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        decision = RulesEngine.evaluate(message_event_text, private_context, [])
        assert decision == RoutingDecision(matched=False)

    def test_catch_all_rule(
        self, message_event_text: MessageEvent, private_context: RoutingContext
    ) -> None:
        rules = [
            RoutingRule(condition={"event_type": "callback_query"}, target="topic_b"),
            RoutingRule(condition={}, target="catch_all"),
        ]
        decision = RulesEngine.evaluate(message_event_text, private_context, rules)
        assert decision == RoutingDecision(matched=True, target="catch_all", rule_idx=1)
