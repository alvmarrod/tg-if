"""Shared utility functions used by admin command modules."""

from __future__ import annotations

from domain.entities import MediaScope


def _parse_kwargs(args: list[str]) -> dict[str, str | None]:
    kwargs: dict[str, str | None] = {}
    i = 0
    while i < len(args):
        if args[i].startswith("--"):
            key = args[i][2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                kwargs[key] = args[i + 1]
                i += 2
            else:
                kwargs[key] = None
                i += 1
        else:
            i += 1
    return kwargs


def _parse_scope(scope_str: str) -> tuple[MediaScope | None, str | None]:
    if scope_str == "global":
        return MediaScope.GLOBAL, None
    if scope_str.startswith("chat:"):
        return MediaScope.CHAT, scope_str[5:]
    if scope_str.startswith("user:"):
        return MediaScope.USER, scope_str[5:]
    return None, None


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def _parse_size(s: str) -> int | None:
    s = s.strip().upper()
    try:
        if s.endswith("GB"):
            return int(float(s[:-2]) * 1024 * 1024 * 1024)
        if s.endswith("MB"):
            return int(float(s[:-2]) * 1024 * 1024)
        if s.endswith("KB"):
            return int(float(s[:-2]) * 1024)
        return int(s)
    except ValueError:
        return None


def _format_uptime(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)
