import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from domain.entities import RoutingContext, TelegramEvent
from domain.rules import RoutingDecision, RoutingRule, RulesEngine, resolve_subtype
from infrastructure.broker import Publisher
from infrastructure.config import BotConfig


logger = structlog.get_logger()


class EventDispatcher:
    def __init__(self, configs: list[BotConfig], publisher: Publisher) -> None:
        self._rules: dict[str, list[RoutingRule]] = {}
        for c in configs:
            self._rules[c.name] = c.routing_rules
        self._publisher = publisher

    async def dispatch(
        self,
        event: TelegramEvent,
        context: RoutingContext,
    ) -> RoutingDecision:
        rules = self._rules.get(event.bot_id)
        if not rules:
            return RoutingDecision(matched=False)

        decision = RulesEngine.evaluate(event, context, rules)

        if decision.matched and decision.target:
            envelope = self._build_envelope(event, context, decision.target)
            await self._publisher.publish(decision.target, envelope)
            logger.info(
                "event routed",
                bot=event.bot_id,
                target=decision.target,
                rule=decision.rule_idx,
            )
        else:
            logger.warning(
                "no matching rule",
                bot=event.bot_id,
                event_type=event.event_type.value,
            )

        return decision

    def _build_envelope(
        self,
        event: TelegramEvent,
        context: RoutingContext,
        target: str,
    ) -> dict[str, Any]:
        return {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "bot_id": event.bot_id,
            "event_type": event.event_type.value,
            "event_subtype": resolve_subtype(event),
            "chat_id": event.chat_id,
            "user_id": event.user_id,
            "routing_context": context.model_dump(),
            "payload": event.raw_payload,
        }
