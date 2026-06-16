from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


@dataclass
class FileInfo:
    bot_id: str
    file_unique_id: str
    ext: str
    size: int
    accesses: int
    last_access: datetime | None
    stored_at: datetime


class AdminSignalType(str, Enum):
    RESPONSE_FAILED = "response_failed"
    COMPONENT_CONNECTED = "component_connected"
    COMPONENT_DISCONNECTED = "component_disconnected"
    CONFIG_WARNING = "config_warning"
