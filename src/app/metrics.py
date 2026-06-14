from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
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


class ServiceMetrics:
    def __init__(self) -> None:
        self.bot_events: defaultdict[str, BotEventMetrics] = defaultdict(
            BotEventMetrics
        )
        self.responses = ResponseMetrics()
        self.started_at: datetime = datetime.now(timezone.utc)

    def event_received(self, bot_id: str) -> None:
        self.bot_events[bot_id].received += 1

    def event_matched(self, bot_id: str) -> None:
        self.bot_events[bot_id].matched += 1

    def event_published(self, bot_id: str) -> None:
        self.bot_events[bot_id].published += 1

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
