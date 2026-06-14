from __future__ import annotations

from collections import deque
from typing import Any


class LogBuffer:
    def __init__(self, max_size: int = 200) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_size)

    def processor(
        self, logger: Any, method_name: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            self._buffer.append(
                {
                    "timestamp": event_dict.get("timestamp", ""),
                    "level": method_name.upper(),
                    "event": event_dict.get("event", ""),
                    "logger": event_dict.get("logger", ""),
                    "extra": {
                        k: v
                        for k, v in event_dict.items()
                        if k not in ("timestamp", "event", "logger")
                    },
                }
            )
        except Exception:
            pass
        return event_dict

    def recent(self, n: int = 20) -> list[dict[str, Any]]:
        return list(self._buffer)[-n:]
