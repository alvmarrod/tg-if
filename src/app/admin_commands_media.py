"""Media-related admin commands (eager/lazy/config/list/stats/prune/purge)."""

from __future__ import annotations

from typing import Any

import structlog

from domain.entities import MediaConfigRule

from app.admin_commands_utils import (
    _format_size,
    _parse_kwargs,
    _parse_scope,
    _parse_size,
)

logger = structlog.get_logger()


class MediaCommandDelegate:
    def __init__(
        self,
        *,
        admin: Any,
        media_config: Any | None,
        storage: Any | None,
    ) -> None:
        self._admin = admin
        self._media_config = media_config
        self._storage = storage

    async def cmd_media_eager(self, chat_id: int, args: list[str]) -> None:
        if self._media_config is None:
            await self._admin.send_text(chat_id, "Media config not available")
            return
        kwargs = _parse_kwargs(args)
        scope_str = kwargs.get("scope")
        if not scope_str:
            await self._admin.send_text(
                chat_id,
                "Usage: /media-eager --scope global|chat:<id>|user:<id> [--type <t>]",
            )
            return

        scope, scope_id = _parse_scope(scope_str)
        if scope is None:
            await self._admin.send_text(chat_id, f"Invalid scope: {scope_str}")
            return

        types_str = kwargs.get("type") or "all"
        content_types = [t.strip() for t in types_str.split(",")]

        rule = MediaConfigRule(
            scope=scope,
            scope_id=scope_id,
            content_types=content_types,
            action="eager",
        )
        self._media_config.add_rule(rule)
        await self._admin.send_text(
            chat_id,
            f"Eager download set: scope={scope_str}, type={types_str}",
        )

    async def cmd_media_lazy(self, chat_id: int, args: list[str]) -> None:
        if self._media_config is None:
            await self._admin.send_text(chat_id, "Media config not available")
            return
        kwargs = _parse_kwargs(args)
        scope_str = kwargs.get("scope")
        if not scope_str:
            await self._admin.send_text(
                chat_id,
                "Usage: /media-lazy --scope global|chat:<id>|user:<id> [--type <t>]",
            )
            return

        scope, scope_id = _parse_scope(scope_str)
        if scope is None:
            await self._admin.send_text(chat_id, f"Invalid scope: {scope_str}")
            return

        types_str = kwargs.get("type") or "all"
        content_types = [t.strip() for t in types_str.split(",")]

        rule = MediaConfigRule(
            scope=scope,
            scope_id=scope_id,
            content_types=content_types,
            action="lazy",
        )
        self._media_config.add_rule(rule)
        await self._admin.send_text(
            chat_id,
            f"Lazy download set: scope={scope_str}, type={types_str}",
        )

    async def cmd_media_config(self, chat_id: int, args: list[str]) -> None:
        if self._media_config is None:
            await self._admin.send_text(chat_id, "Media config not available")
            return
        rules = self._media_config.list_rules()
        if not rules:
            await self._admin.send_text(chat_id, "No media config rules")
            return

        lines = ["Media config rules:"]
        for i, r in enumerate(rules, 1):
            sid = f":{r.scope_id}" if r.scope_id else ""
            lines.append(
                f"  {i}. {r.scope}{sid} types={','.join(r.content_types)} -> {r.action}"
            )
        await self._admin.send_text(chat_id, "\n".join(lines))

    async def cmd_media_list(self, chat_id: int, args: list[str]) -> None:
        if self._storage is None:
            await self._admin.send_text(chat_id, "Storage not available")
            return
        kwargs = _parse_kwargs(args)
        sort_spec = kwargs.get("sort") or "size:desc"
        files = await self._storage.list_files()

        if not files:
            await self._admin.send_text(chat_id, "No cached media")
            return

        sort_cols = [s.strip() for s in sort_spec.split(",")]
        for col_dir in reversed(sort_cols):
            parts = col_dir.split(":")
            col = parts[0]
            reverse = len(parts) < 2 or parts[1] != "asc"
            if col == "size":
                files.sort(key=lambda f: f.size, reverse=reverse)
            elif col == "accesses":
                files.sort(key=lambda f: f.accesses, reverse=reverse)
            elif col == "lru":
                files.sort(
                    key=lambda f: f.last_access.timestamp() if f.last_access else 0,
                    reverse=reverse,
                )
            elif col == "stored_at":
                files.sort(key=lambda f: f.stored_at.timestamp(), reverse=reverse)

        lines = [
            "Cached media:",
            f"{'file_unique_id':<18} {'type':<6} {'size':>10} "
            f"{'accesses':>9} {'last_access':<20} {'stored_at':<20}",
        ]
        for f in files:
            la = f.last_access.strftime("%Y-%m-%d %H:%M") if f.last_access else "—"
            sa = f.stored_at.strftime("%Y-%m-%d %H:%M") if f.stored_at else "—"
            size_str = _format_size(f.size)
            lines.append(
                f"{f.file_unique_id:<18} {f.ext:<6} {size_str:>10} "
                f"{f.accesses:>9} {la:<20} {sa:<20}"
            )
        await self._admin.send_text(chat_id, "\n".join(lines))

    async def cmd_media_stats(self, chat_id: int) -> None:
        if self._storage is None:
            await self._admin.send_text(chat_id, "Storage not available")
            return
        stats = await self._storage.stats()
        lines = [
            "Media cache statistics:",
            f"  Total files: {stats['total_files']}",
            f"  Total size:  {_format_size(stats['total_size_bytes'])}",
        ]
        by_type = stats.get("by_type", {})
        if by_type:
            lines.append("  By type:")
            for ext in sorted(by_type):
                info = by_type[ext]
                lines.append(
                    f"    .{ext:<5} {info['count']:>6} files, "
                    f"{_format_size(info['size_bytes'])}"
                )
        await self._admin.send_text(chat_id, "\n".join(lines))

    async def cmd_media_prune(self, chat_id: int, args: list[str]) -> None:
        if self._storage is None:
            await self._admin.send_text(chat_id, "Storage not available")
            return
        kwargs = _parse_kwargs(args)

        keep_first: int | None = None
        max_size: int | None = None
        older_than_days: int | None = None

        keep_str = kwargs.get("keep-first")
        if keep_str:
            try:
                keep_first = int(keep_str)
            except ValueError:
                await self._admin.send_text(
                    chat_id, f"Invalid --keep-first value: {keep_str}"
                )
                return

        max_size_str = kwargs.get("max-size")
        if max_size_str:
            max_size = _parse_size(max_size_str)
            if max_size is None:
                await self._admin.send_text(
                    chat_id, f"Invalid --max-size value: {max_size_str}"
                )
                return

        older_str = kwargs.get("older-than")
        if older_str:
            try:
                older_than_days = int(older_str.rstrip("d"))
            except ValueError:
                await self._admin.send_text(
                    chat_id, f"Invalid --older-than value: {older_str}"
                )
                return

        if keep_first is None and max_size is None and older_than_days is None:
            await self._admin.send_text(
                chat_id,
                "Usage: /media-prune --keep-first N | --max-size N[KB|MB|GB] | --older-than Nd",
            )
            return

        deleted = await self._storage.prune(
            keep_first=keep_first,
            max_size=max_size,
            older_than_days=older_than_days,
        )
        await self._admin.send_text(
            chat_id, f"Pruned {deleted} file{'s' if deleted != 1 else ''}"
        )

    async def cmd_media_purge(self, chat_id: int, args: list[str]) -> None:
        if self._storage is None:
            await self._admin.send_text(chat_id, "Storage not available")
            return
        if not args or args[0] != "confirm":
            stats = await self._storage.stats()
            await self._admin.send_text(
                chat_id,
                f"⚠️ This will delete all {stats['total_files']} cached files "
                f"({_format_size(stats['total_size_bytes'])}). "
                "Send /media-purge confirm to proceed.",
            )
            return

        deleted = await self._storage.purge()
        await self._admin.send_text(
            chat_id, f"Purged {deleted} file{'s' if deleted != 1 else ''}"
        )
