import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from app.metrics import ServiceMetrics
from domain.entities import RoutingContext, TelegramEvent
from infrastructure import metrics_exporter as prom
from domain.rules import RoutingDecision, RoutingRule, RulesEngine, resolve_subtype
from infrastructure.broker import Publisher
from infrastructure.config import BotConfig


logger = structlog.get_logger()


class EventDispatcher:
    def __init__(
        self,
        configs: list[BotConfig],
        publisher: Publisher,
        metrics: ServiceMetrics | None = None,
        media_base_url: str = "http://localhost:8080",
    ) -> None:
        self._rules: dict[str, list[RoutingRule]] = {}
        for c in configs:
            self._rules[c.name] = c.routing_rules
        self._publisher = publisher
        self._metrics = metrics
        self._media_base_url = media_base_url.rstrip("/")

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
            if self._metrics:
                self._metrics.event_matched(event.bot_id)
            prom.events_matched.labels(bot=event.bot_id).inc()
            envelope = self._build_envelope(event, context, decision.target)
            await self._publisher.publish(decision.target, envelope)
            if self._metrics:
                self._metrics.event_published(event.bot_id)
            prom.events_published.labels(bot=event.bot_id).inc()
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
        file_id: str | None = None
        file_unique_id: str | None = None
        if hasattr(event, "file_id"):
            file_id = getattr(event, "file_id")
        if hasattr(event, "file_unique_id"):
            file_unique_id = getattr(event, "file_unique_id")

        media_url: str | None = None
        if file_unique_id and hasattr(event, "bot_id"):
            base = f"{self._media_base_url}/files/{event.bot_id}/{file_unique_id}"
            if file_id:
                base += f"?file_id={file_id}"
            media_url = base

        envelope: dict[str, Any] = {
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

        if file_id:
            envelope["file_id"] = file_id
        if file_unique_id:
            envelope["file_unique_id"] = file_unique_id
        if hasattr(event, "media_status"):
            envelope["media_status"] = getattr(event, "media_status")
        if media_url:
            envelope["media_url"] = media_url

        return envelope
