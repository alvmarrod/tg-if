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


@dataclass
class UploadEntry:
    content_hash: str
    url_hash: str | None = None
    url: str | None = None
    file_id: str | None = None
    file_unique_id: str | None = None
    bot_id: str = ""
    ext: str = "bin"
    size: int = 0
    created_at: float = 0.0
    last_used_at: float = 0.0
    use_count: int = 0


class AdminSignalType(str, Enum):
    RESPONSE_FAILED = "response_failed"
    COMPONENT_CONNECTED = "component_connected"
    COMPONENT_DISCONNECTED = "component_disconnected"
    CONFIG_WARNING = "config_warning"
