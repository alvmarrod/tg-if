from __future__ import annotations

from collections import deque
from collections.abc import MutableMapping
from typing import Any


class LogBuffer:
    """A bounded buffer for storing recent log events."""

    def __init__(self, max_size: int = 200) -> None:
        """Initialize the log buffer.

        Args:
            max_size: Maximum number of events to store (default 200)

        Raises:
            ValueError: If max_size is not positive
        """
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_size)

    def processor(
        self, logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        """Process and buffer a log event.

        Args:
            logger: The logger instance
            method_name: The logging method name (e.g., 'info', 'error')
            event_dict: The event dictionary to buffer

        Returns:
            The original event_dict

        Raises:
            ValueError: If event_dict is None
        """
        if event_dict is None:
            raise ValueError("event_dict cannot be None")
        if not event_dict:
            # Skip buffering empty event dicts
            return event_dict
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
        """Get the most recent n buffered log events.

        Args:
            n: Number of recent events to return (default 20)

        Returns:
            List of the most recent log events
        """
        if n <= 0:
            return []
        return list(self._buffer)[-n:]
