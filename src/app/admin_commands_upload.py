"""Upload-related admin commands (list/prune/purge)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from app.admin_commands_utils import _format_size, _parse_kwargs, _parse_size

logger = structlog.get_logger()


class UploadCommandDelegate:
    def __init__(
        self,
        *,
        admin: Any,
        upload_registry: Any,
        upload_storage: Any | None,
    ) -> None:
        self._admin = admin
        self._upload_registry = upload_registry
        self._upload_storage = upload_storage

    async def cmd_upload_list(self, chat_id: int, args: list[str]) -> None:
        if self._upload_registry is None:
            await self._admin.send_text(chat_id, "Upload registry not available")
            return
        kwargs = _parse_kwargs(args)
        sort_spec = kwargs.get("sort") or "uses:desc"
        bot_filter = kwargs.get("bot")

        entries = await self._upload_registry.list_all(bot_id=bot_filter)
        if not entries:
            await self._admin.send_text(chat_id, "No upload records")
            return

        sort_cols = [s.strip() for s in sort_spec.split(",")]
        for col_dir in reversed(sort_cols):
            parts = col_dir.split(":")
            col = parts[0]
            reverse = len(parts) < 2 or parts[1] != "asc"
            if col == "hash":
                entries.sort(key=lambda e: e.content_hash, reverse=reverse)
            elif col == "bot":
                entries.sort(key=lambda e: e.bot_id, reverse=reverse)
            elif col == "ext":
                entries.sort(key=lambda e: e.ext, reverse=reverse)
            elif col == "size":
                entries.sort(key=lambda e: e.size, reverse=reverse)
            elif col == "uses":
                entries.sort(key=lambda e: e.use_count, reverse=reverse)
            elif col == "lru":
                entries.sort(key=lambda e: e.last_used_at, reverse=reverse)
            elif col == "created_at":
                entries.sort(key=lambda e: e.created_at, reverse=reverse)

        lines = [
            "Upload records:",
            f"{'hash':<14} {'bot':<12} {'ext':<5} {'size':>10} "
            f"{'fid':>4} {'uses':>5} {'last_used':<20} {'created':<20}",
        ]
        for e in entries:
            fid_mark = "✅" if e.file_id else "❌"
            lu = (
                datetime.fromtimestamp(e.last_used_at, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M"
                )
                if e.last_used_at
                else "—"
            )
            ca = (
                datetime.fromtimestamp(e.created_at, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M"
                )
                if e.created_at
                else "—"
            )
            size_str = _format_size(e.size)
            lines.append(
                f"{e.content_hash[:12]:<14} {e.bot_id:<12} {e.ext:<5} "
                f"{size_str:>10} {fid_mark:>4} {e.use_count:>5} {lu:<20} {ca:<20}"
            )
        await self._admin.send_text(chat_id, "\n".join(lines))

    async def cmd_upload_prune(self, chat_id: int, args: list[str]) -> None:
        if self._upload_registry is None or self._upload_storage is None:
            await self._admin.send_text(chat_id, "Upload service not available")
            return
        kwargs = _parse_kwargs(args)
        bot_filter = kwargs.get("bot")

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
                "Usage: /upload-prune "
                "--keep-first N | --max-size N[KB|MB|GB] | --older-than Nd [--bot <n>]",
            )
            return

        entries = await self._upload_registry.list_all(bot_id=bot_filter)
        if not entries:
            await self._admin.send_text(chat_id, "No upload records to prune")
            return

        candidates: list[Any] = list(entries)
        now = datetime.now(timezone.utc).timestamp()

        if older_than_days is not None:
            cutoff = now - older_than_days * 86400
            candidates = [e for e in candidates if e.last_used_at < cutoff]

        if keep_first is not None:
            candidates.sort(key=lambda e: e.last_used_at, reverse=True)
            candidates = candidates[keep_first:]

        if max_size is not None:
            candidates.sort(key=lambda e: e.last_used_at, reverse=True)
            kept: list[Any] = []
            running = 0
            for e in sorted(entries, key=lambda e: e.last_used_at, reverse=True):
                if e.size + running > max_size:
                    break
                kept.append(e)
                running += e.size
            kept_hashes = {e.content_hash for e in kept}
            candidates = [e for e in candidates if e.content_hash not in kept_hashes]

        deleted = 0
        for e in candidates:
            try:
                await self._upload_storage.delete(e.bot_id, e.content_hash)
            except Exception:
                logger.warning(
                    "upload storage delete failed during prune",
                    bot=e.bot_id,
                    content_hash=e.content_hash,
                    exc_info=True,
                )
            await self._upload_registry.delete(e.content_hash)
            deleted += 1

        await self._admin.send_text(
            chat_id,
            f"Pruned {deleted} upload record{'s' if deleted != 1 else ''}",
        )

    async def cmd_upload_purge(self, chat_id: int, args: list[str]) -> None:
        if self._upload_registry is None or self._upload_storage is None:
            await self._admin.send_text(chat_id, "Upload service not available")
            return
        kwargs = _parse_kwargs(args)
        bot_filter = kwargs.get("bot")

        entries = await self._upload_registry.list_all(bot_id=bot_filter)
        if not entries:
            await self._admin.send_text(chat_id, "No upload records to purge")
            return

        if not args or args[0] != "confirm":
            total_size = sum(e.size for e in entries)
            await self._admin.send_text(
                chat_id,
                f"⚠️ This will delete all {len(entries)} upload record"
                f"{'s' if len(entries) != 1 else ''} "
                f"({_format_size(total_size)}). "
                "Send /upload-purge confirm to proceed.",
            )
            return

        deleted = 0
        for e in entries:
            try:
                await self._upload_storage.delete(e.bot_id, e.content_hash)
            except Exception:
                logger.warning(
                    "upload storage delete failed during purge",
                    bot=e.bot_id,
                    content_hash=e.content_hash,
                    exc_info=True,
                )
            await self._upload_registry.delete(e.content_hash)
            deleted += 1

        await self._admin.send_text(
            chat_id,
            f"Purged {deleted} upload record{'s' if deleted != 1 else ''}",
        )
