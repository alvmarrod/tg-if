from typing import Any

from pydantic import BaseModel, Field

from domain.entities import (
    CallbackQueryEvent,
    CommandEvent,
    MessageEvent,
    RoutingContext,
    TelegramEvent,
)


class RoutingRule(BaseModel):
    condition: dict[str, Any] = Field(default_factory=dict)
    target: str


class RoutingDecision(BaseModel):
    matched: bool
    target: str | None = None
    rule_idx: int | None = None


def resolve_subtype(event: TelegramEvent) -> str | None:
    if isinstance(event, MessageEvent):
        return event.media_type or "text"
    if isinstance(event, (CommandEvent, CallbackQueryEvent)):
        return "text"
    return None


def _match_condition(
    condition: dict[str, Any],
    event: TelegramEvent,
    context: RoutingContext,
) -> bool:
    if not condition:
        return True

    actual: Any
    for key, expected in condition.items():
        if key == "event_type":
            actual = event.event_type.value
        elif key == "event_subtype":
            actual = resolve_subtype(event)
        elif key == "chat_type":
            actual = context.chat_type.value
        elif key == "command":
            actual = context.command
        elif key == "command_starts_with":
            if not context.command or not context.command.startswith(expected):
                return False
            continue
        elif key == "has_media":
            actual = context.has_media
        elif key == "media_type":
            actual = context.media_type
        elif key == "user_role":
            actual = context.user_role
        else:
            continue

        if actual != expected:
            return False

    return True


class RulesEngine:
    @staticmethod
    def evaluate(
        event: TelegramEvent,
        context: RoutingContext,
        rules: list[RoutingRule],
    ) -> RoutingDecision:
        for idx, rule in enumerate(rules):
            if _match_condition(rule.condition, event, context):
                return RoutingDecision(matched=True, target=rule.target, rule_idx=idx)
        return RoutingDecision(matched=False)
