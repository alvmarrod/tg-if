from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class BotEventMetrics:
    received: int = 0
    matched: int = 0
    published: int = 0


@dataclass
class ResponseMetrics:
    consumed: int = 0
    sent: int = 0
    failed: int = 0


@dataclass
class TargetMetrics:
    events: int = 0
    last_event: datetime | None = None
    bots: set[str] = field(default_factory=set)


@dataclass
class TargetStat:
    name: str
    events: int
    last_event: datetime | None
    bots: list[str]


class ServiceMetrics:
    def __init__(self) -> None:
        self.bot_events: defaultdict[str, BotEventMetrics] = defaultdict(
            BotEventMetrics
        )
        self.responses = ResponseMetrics()
        self.started_at: datetime = datetime.now(timezone.utc)
        self.per_target: dict[str, TargetMetrics] = {}
        self.target_window_start: datetime = datetime.now(timezone.utc)

    def event_received(self, bot_id: str) -> None:
        self.bot_events[bot_id].received += 1

    def event_matched(self, bot_id: str) -> None:
        self.bot_events[bot_id].matched += 1

    def event_published(self, bot_id: str) -> None:
        self.bot_events[bot_id].published += 1

    def target_event(self, bot_id: str, target: str) -> None:
        now = datetime.now(timezone.utc)
        if (now - self.target_window_start).total_seconds() >= 3600:
            self.per_target.clear()
            self.target_window_start = now
        tm = self.per_target.setdefault(target, TargetMetrics())
        tm.events += 1
        tm.last_event = now
        tm.bots.add(bot_id)

    def get_target_stats(self) -> list[TargetStat]:
        sorted_items = sorted(
            self.per_target.items(),
            key=lambda x: x[1].events,
            reverse=True,
        )
        result: list[TargetStat] = []
        for name, tm in sorted_items:
            result.append(
                TargetStat(
                    name=name,
                    events=tm.events,
                    last_event=tm.last_event,
                    bots=sorted(tm.bots),
                )
            )
        return result

    def get_target(self, name: str) -> TargetStat | None:
        tm = self.per_target.get(name)
        if tm is None:
            return None
        return TargetStat(
            name=name,
            events=tm.events,
            last_event=tm.last_event,
            bots=sorted(tm.bots),
        )

    def response_consumed(self) -> None:
        self.responses.consumed += 1

    def response_sent(self) -> None:
        self.responses.sent += 1

    def response_failed(self) -> None:
        self.responses.failed += 1

    def snapshot(self) -> dict[str, Any]:
        uptime = datetime.now(timezone.utc) - self.started_at
        return {
            "uptime_seconds": int(uptime.total_seconds()),
            "bot_events": {
                bid: {
                    "received": m.received,
                    "matched": m.matched,
                    "published": m.published,
                }
                for bid, m in self.bot_events.items()
            },
            "responses": {
                "consumed": self.responses.consumed,
                "sent": self.responses.sent,
                "failed": self.responses.failed,
            },
        }
